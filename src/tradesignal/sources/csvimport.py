"""CSV-импорт в оба контура: статистика (A) и компании/поставки (B).

Три шаблона (примеры в examples/): stat CSV, companies CSV, shipments CSV.
Происхождение фиксируется source=import:<файл>; raw_ref указывает на файл.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import (CompanyRecord, StatRow, forwarder_suspect, utcnow)

# числовые коды → ISO3, единообразно с comtrade-коннектором
_NUMERIC_TO_ISO3 = {
    "0": "WLD", "156": "CHN", "392": "JPN", "410": "KOR", "356": "IND",
    "704": "VNM", "764": "THA", "458": "MYS", "360": "IDN", "276": "DEU",
    "826": "GBR", "842": "USA", "250": "FRA", "380": "ITA", "528": "NLD",
    "724": "ESP", "616": "POL", "752": "SWE", "756": "CHE", "792": "TUR",
    "203": "CZE", "642": "ROU", "124": "CAN", "484": "MEX", "76": "BRA",
    "36": "AUS", "710": "ZAF", "784": "ARE", "682": "SAU", "376": "ISR",
}


def _to_iso3(value: str | None) -> str:
    code = str(value or "").strip().upper()
    return _NUMERIC_TO_ISO3.get(code, code)


def import_stat_csv(path: Path, source_tag: str = "import") -> list[StatRow]:
    rows: list[StatRow] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            get = lambda *keys: next(
                (raw[k] for k in keys if raw.get(k) not in (None, "",)), None)
            hs = str(get("hs_code", "hs") or "").strip()
            period = str(get("period") or "").strip()
            if not hs or not period:
                continue
            value = _num(get("value_usd", "value"))
            rows.append(StatRow(
                source=get("source") or source_tag,
                reporter_iso=_to_iso3(get("reporter_iso", "reporter")),
                partner_iso=_to_iso3(get("partner_iso", "partner")) or "WLD",
                flow=str(get("flow") or "M"),
                hs_code=hs, period=period,
                value_usd=value,
                qty=_num(get("qty")),
                qty_unit=get("qty_unit"),
                raw_ref=str(path)))
    return rows


def import_companies_csv(path: Path, source_tag: str = "import") -> list[CompanyRecord]:
    out: list[CompanyRecord] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            get = lambda *keys: next(
                (raw[k] for k in keys if raw.get(k) not in (None, "",)), None)
            name = (get("name", "company") or "").strip()
            source_key = str(get("source_key", "id") or name.lower()).strip()
            if not name:
                continue
            out.append(CompanyRecord(
                source=get("source") or source_tag,
                source_key=source_key,
                name=name,
                name_norm=normalize_name(name),
                country=get("country"),
                website=get("website"),
                identity_confidence=str(get("identity_confidence") or "medium")))
    return out


def import_shipments_csv(path: Path, companies: dict[str, int]) -> list[dict]:
    """companies: source_key → company_id (после upsert companies)."""
    out: list[dict] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            get = lambda *keys: next(
                (raw[k] for k in keys if raw.get(k) not in (None, "",)), None)
            company_key = str(get("company_key", "company_source_key") or "")
            company_id = companies.get(company_key)
            supplier = (get("supplier_name", "supplier") or "").strip()
            arrival = (get("arrival_date", "date") or "").strip()
            if company_id is None or not supplier or not arrival:
                continue
            name = get("company_name") or ""
            out.append({
                "source": get("source") or "import",
                "company_id": company_id,
                "supplier_name": supplier,
                "supplier_country": get("supplier_country"),
                "arrival_date": arrival,
                "port": get("port"),
                "hs_codes": get("hs_codes"),
                "weight_kg_declared": _num(get("weight_kg", "weight_kg_declared")),
                "quantity_declared": _num(get("quantity", "quantity_declared")),
                "ff_suspect": forwarder_suspect(supplier) or forwarder_suspect(name),
                "raw_ref": str(path),
                "observed_at": utcnow(),
            })
    return out


def normalize_name(name: str) -> str:
    lowered = name.lower()
    for marker in (", inc.", " inc.", ", llc", " llc", ", ltd", " ltd",
                   ", gmbh", " gmbh", " co.", " ltd.", " s.a.", " bv", " oy"):
        lowered = lowered.replace(marker, "")
    return " ".join(lowered.split())


def _num(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace(" ", ""))
    except ValueError:
        return None
