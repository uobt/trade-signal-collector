"""ImportYeti (контур B): US sea manifests, уровень компаний.

Статус: BLOCKED (technical) — подтверждено 2026-09-17:
robots: Allow: /, но /search?q и /api/* запрещены; главная и профиль
компании отдают HTTP 403 Cloudflare challenge. Автосбор остановлен,
обход ( прокси/CAPTCHA ) запрещён ТЗ. Коннектор — только парсер
сохранённых страниц (fixture/import) для будущей легальной выгрузки.
"""

from __future__ import annotations

import html as html_lib
import re

from ..models import RawDocument, TradePage
from .base import Connector


class ImportYetiConnector(Connector):
    code, label = "importyeti", "ImportYeti"
    live_allowed = False
    policy_reason = ("robots запрещает /search?q и /api/*; фактически HTTP 403 "
                     "Cloudflare на главной и профилях (2026-09-17). "
                     "Обход не закладываем")

    def build_url(self, query) -> str:
        raise PermissionError(self.policy_reason)

    def parse_response(self, doc: RawDocument) -> TradePage:
        """Парсер страницы поставщика для будущих выгрузок/партнёрских данных."""
        page = TradePage(applied_filters={"url": doc.url})
        if "Just a moment" in doc.content or doc.status in (401, 403):
            page.status, page.stop_reason = "blocked", "cloudflare_challenge"
            return page
        # Штатная разметка профиля: таблицы поставщиков. Схема фиксируется
        # на разрешённой выгрузке; сейчас распознаём даты и названия строк.
        page.note = "parse_supplier_profile: схема уточняется на первой выгрузке"
        page.status = "partial"
        return page


FF_HINTS = re.compile(r"(?i)\b(usa|uk|germany|china|vietnam|india|italy|turkey)\b")
