"""Планировщик: прогоны по запросам, лимиты, raw-first, честные статусы."""

from __future__ import annotations

from dataclasses import dataclass

from .models import SourceBlocked, TradeSpec
from .rawstore import save_raw
from .storage import Store
from .transports.http import HttpTransport, TransportError


@dataclass
class QueryReport:
    source: str
    url: str
    status: str
    rows: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    note: str | None = None


def run_queries(spec: TradeSpec, connector, store: Store, run_id: int,
                data_root, dry_run: bool = False,
                min_delay_seconds: float = 0.0) -> list[QueryReport]:
    """Выполняет запросы через коннектор; dry-run не делает сеть."""
    reports: list[QueryReport] = []
    requests_planned = len(spec.queries)
    transport = HttpTransport(
        delay_seconds=max(spec.transport.request_delay_seconds,
                          min_delay_seconds),
        timeout=spec.transport.timeout_seconds,
        max_retries=spec.transport.max_retries,
        budget_requests=requests_planned * 4)

    # Развёртка по периодам: preview-канал принимает 1 период на запрос
    tasks = []
    for query in spec.queries:
        max_periods = getattr(connector, "max_periods", 20)
        periods = query.periods or [""]
        for index in range(0, len(periods), max_periods):
            chunk = periods[index:index + max_periods]
            from dataclasses import replace
            tasks.append(replace(query, periods=chunk))

    for query in tasks:
        url = connector.build_url(query)
        if dry_run:
            reports.append(QueryReport(connector.code, url, "dry_run"))
            continue
        try:
            headers = connector.headers() if hasattr(connector, "headers") else {}
            doc = transport.get(url, extra_headers=headers)
        except TransportError as exc:
            store.note_run(run_id, note=str(exc))
            reports.append(QueryReport(connector.code, url,
                                       "blocked" if exc.blocked else "failed",
                                       note=str(exc)))
            if exc.blocked:
                break
            continue
        raw_ref = save_raw(data_root, connector.code, doc)
        page = connector.parse_response(doc)
        report = QueryReport(connector.code, url, page.status)
        for row in page.rows[: spec.max_rows_per_query]:
            row.raw_ref = raw_ref
            event = store.upsert_stat(row)
            if event == "first_seen":
                report.new += 1
            elif event == "updated":
                report.updated += 1
            else:
                report.unchanged += 1
            report.rows += 1
        report.note = page.note
        reports.append(report)
    store.note_run(run_id, requests=len(reports),
                   rows=sum(r.rows for r in reports),
                   new_rows=sum(r.new for r in reports),
                   updated_rows=sum(r.updated for r in reports))
    return reports
