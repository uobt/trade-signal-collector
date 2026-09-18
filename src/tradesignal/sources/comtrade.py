"""UN Comtrade (контур A): официальная статистика ООН по странам/HS.

Два режима:
- preview (public/v1/preview, БЕЗ ключа): полная разбивка с total-строками
  и жёсткий rate limit (~1 запрос/мин, 429 → пауза ≥30с);
- data (data/v1/get, с ключом comtrade - v1): полноценный канал,
  поддерживает aggregateBy.

Ключ: бесплатная регистрация comtradeplus.un.org, заголовок
Ocp-Apim-Subscription-Key. Лимиты подписки фиксировать по факту.
"""

from __future__ import annotations

import urllib.parse

from ..models import (RawDocument, StatRow, TradePage, TradeQuery)
from .base import Connector

DATA_BASE = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
PREVIEW_BASE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
KEY_HEADER = "Ocp-Apim-Subscription-Key"

# ISO3 → M49/numeric (подмножество пилота + частые партнёры)
ISO3_NUMERIC = {
    "DEU": "276", "GBR": "826", "USA": "842", "FRA": "250", "ITA": "380",
    "NLD": "528", "ESP": "724", "POL": "616", "SWE": "752", "CHE": "756",
    "TUR": "792", "CZE": "203", "ROU": "642", "AUT": "040", "BEL": "056",
    "IRL": "372", "DNK": "208", "FIN": "246", "NOR": "578", "PRT": "620",
    "CHN": "156", "JPN": "392", "KOR": "410", "IND": "356", "VNM": "704",
    "THA": "764", "MYS": "458", "IDN": "360", "CAN": "124", "MEX": "484",
    "BRA": "076", "AUS": "036", "NZL": "554", "ZAF": "710", "ARE": "784",
    "SAU": "682", "ISR": "376", "WLD": "0",
}
NUMERIC_TO_ISO3 = {v: k for k, v in ISO3_NUMERIC.items()}


def numeric(iso3: str) -> str:
    code = iso3.upper()
    if code.isdigit():
        return code
    if code not in ISO3_NUMERIC:
        raise ValueError(f"нет ISO3→numeric маппинга для {iso3!r}; "
                         "добавь в ISO3_NUMERIC")
    return ISO3_NUMERIC[code]


def _to_iso3(code) -> str:
    return NUMERIC_TO_ISO3.get(str(code), str(code))


def _is_total_line(record: dict) -> bool:
    """Total-строка preview: partner2=0 (весь мир), customs C00 (все режимы),
    mot=0 (весь транспорт). Проверено 2026-09-18 на DEU×CHN×HS8422×2024:
    контрольная сумма разбивок совпала с total-строкой до центов."""
    return (str(record.get("partner2Code")) == "0"
            and str(record.get("customsCode")) in ("C00", "")
            and int(record.get("motCode") or 0) == 0)


class ComtradeConnector(Connector):
    code, label = "comtrade", "UN Comtrade"

    def __init__(self, api_key: str = "", mode: str = "data"):
        self.api_key = api_key
        self.mode = mode  # "data" (с ключом) | "preview" (без ключа)
        if mode == "preview":
            self.code = "comtrade-preview"
        # preview: максимум 1 период на запрос (проверено 2026-09-18:
        # "Maximum number of periods for preview is 1"); data/v1/get — csv-список
        self.max_periods = 1 if mode == "preview" else 20

    @property
    def base(self) -> str:
        return PREVIEW_BASE if self.mode == "preview" else DATA_BASE

    def build_url(self, query: TradeQuery) -> str:
        params = {
            "reporterCode": numeric(query.reporter),
            "partnerCode": numeric(query.partner),
            "flowCode": query.flow,
            "cmdCode": query.hs,
            "period": ",".join(query.periods),
        }
        return self.base + "?" + urllib.parse.urlencode(params)

    def headers(self) -> dict[str, str]:
        if self.mode == "preview" or not self.api_key:
            return {}
        return {KEY_HEADER: self.api_key}

    def parse_response(self, doc: RawDocument) -> TradePage:
        page = TradePage(applied_filters={"url": doc.url})
        payload = _json(doc.content)
        if payload is None:
            page.status, page.stop_reason = "failed", "invalid_json"
            return page
        records = payload.get("data")
        if not isinstance(records, list):
            page.status, page.stop_reason = "failed", "no_data_field"
            page.note = str(payload)[:300]
            return page

        groups: dict[tuple, list[dict]] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            key = (_to_iso3(record.get("reporterCode")),
                   _to_iso3(record.get("partnerCode")),
                   str(record.get("flowCode") or ""),
                   str(record.get("cmdCode") or ""),
                   str(record.get("period") or ""))
            if not all(key):
                continue
            groups.setdefault(key, []).append(record)

        for key, lines in groups.items():
            reporter, partner, flow, hs, period = key
            total = next((r for r in lines if _is_total_line(r)), None)
            fallback_sum = None
            if total is None:
                # partner2=0, mot=0, customs C01/C04 (без C00): C00 = C01+C04
                parts = [r for r in lines
                         if str(r.get("partner2Code")) == "0"
                         and int(r.get("motCode") or 0) == 0
                         and str(r.get("customsCode")) in ("C01", "C04")]
                if parts:
                    fallback_sum = sum(
                        float(r.get("primaryValue") or 0) for r in parts)
            value = total.get("primaryValue") if total else fallback_sum
            if value is None:
                page.unsupported_filters.append(
                    f"нет total-строки: {key}; строк={len(lines)}")
                continue
            qty_src = total.get("qty") if total else None
            page.rows.append(StatRow(
                source=self.code, reporter_iso=reporter, partner_iso=partner,
                flow=flow, hs_code=hs, period=period,
                value_usd=float(value) if value is not None else None,
                qty=float(qty_src) if isinstance(qty_src, (int, float)) else None,
                qty_unit=str(total.get("qtyUnitAbbr")) if total and
                total.get("qtyUnitAbbr") else None))
        page.status = "success"
        if page.unsupported_filters:
            page.status, page.stop_reason = "partial", "no_total_row"
        elif not page.rows:
            page.stop_reason = "exhausted"
        return page


def _json(text: str):
    import json
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
