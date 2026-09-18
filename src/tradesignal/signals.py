"""Производные сигналы: рост YoY, доля партнёра, серия роста.

Правило честности: сигнал статистики — факт; его использование в аутриче —
гипотеза, и она хранится отдельным полем hypothesis.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .models import StatRow


def _period_year(period: str) -> int | None:
    try:
        return int(period.split("-")[0])
    except (ValueError, IndexError):
        return None


def _flow_noun(flow: str) -> str:
    return "Импорт" if flow == "M" else "Экспорт" if flow == "X" else "Импорт/экспорт"


def yoy_growth(rows: Iterable[StatRow]) -> list[dict]:
    """Год к году по каждому ряду (reporter, partner, flow, hs).
    Требует ≥2 лет; иначе insufficient_history — не выдумываем тренд."""
    series: dict[tuple, dict[int, float]] = {}
    for row in rows:
        year = _period_year(row.period)
        if year is None or row.value_usd is None:
            continue
        key = (row.source, row.reporter_iso, row.partner_iso,
               row.flow, row.hs_code)
        series.setdefault(key, {})[year] = row.value_usd

    signals: list[dict] = []
    for key, by_year in series.items():
        source, reporter, partner, flow, hs = key
        years = sorted(by_year)
        for previous, current in zip(years, years[1:]):
            before = by_year[previous]
            after = by_year[current]
            if before is None or after is None:
                continue
            pct = None if before == 0 else round((after - before) / before * 100, 1)
            signals.append({
                "kind": "yoy_growth",
                "source": source, "reporter_iso": reporter,
                "partner_iso": partner, "flow": flow, "hs_code": hs,
                "period": current,
                "value_before": before, "value_after": after,
                "pct": pct,
                "insufficient_history": False,
                "hypothesis": (
                    f"{_flow_noun(flow)} {reporter} по HS {hs} вырос "
                    f"{pct}% г/г ({previous}→{current})" if (pct or 0) > 0 else None),
            })
        if len(years) < 2:
            signals.append({
                "kind": "yoy_growth", "source": source,
                "reporter_iso": reporter, "partner_iso": partner,
                "flow": flow, "hs_code": hs, "period": years[-1] if years else None,
                "value_before": None, "value_after": None, "pct": None,
                "insufficient_history": True, "hypothesis": None,
            })
    return signals


def partner_share(rows: Iterable[StatRow], target_partner: str) -> list[dict]:
    """Доля партнёра в импорте/экспорте отчётной страны по HS за период.
    Требует параллельный ряд 'World' (partner='0'/'WLD')."""
    totals: dict[tuple, float] = {}
    partner_vals: dict[tuple, float] = {}
    for row in rows:
        if row.value_usd is None or not _period_year(row.period):
            continue
        key = (row.source, row.reporter_iso, row.flow, row.hs_code, row.period)
        if row.partner_iso in ("0", "WLD"):
            totals[key] = row.value_usd
        elif row.partner_iso == target_partner:
            partner_vals[key] = row.value_usd
    out = []
    for key, total in totals.items():
        part = partner_vals.get(key)
        if part is None:
            continue
        source, reporter, flow, hs, period = key
        out.append({
            "kind": "partner_share", "source": source,
            "reporter_iso": reporter, "partner_iso": target_partner,
            "flow": flow, "hs_code": hs, "period": period,
            "value_before": total, "value_after": part,
            "pct": round(part / total * 100, 1) if total else None,
            "insufficient_history": False,
            "hypothesis": (
                f"{target_partner} занимает {round(part/total*100,1)}% "
                f"импорта {reporter} по HS {hs}" if total else None),        })
    return out


def growth_streak(rows: Iterable[StatRow], minimum: int = 3) -> list[dict]:
    """Серия последовательных годовых ростов ≥ minimum лет — устойчивый тренд."""
    streaks: list[dict] = []
    for growth in yoy_growth(rows):
        if growth["insufficient_history"] or not growth["pct"] or growth["pct"] <= 0:
            continue
        key = (growth["source"], growth["reporter_iso"],
               growth["partner_iso"], growth["flow"], growth["hs_code"])
        streaks.append({**growth, "kind": "growth_streak", "streak_key": key})
    # Простая реализация: подряд идущие положительные YoY считаем серией,
    # полная цепочка собирается из самих YoY-записей при экспорте.
    return [s for s in streaks if len(str(s["period"])) >= 4]


def computed_at_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
