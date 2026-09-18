"""Базовые контракты коннекторов."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import RawDocument, TradePage, TradeQuery


class Connector(ABC):
    code: str = ""
    label: str = ""
    live_allowed: bool = True
    policy_reason: str = ""

    @abstractmethod
    def build_url(self, query: TradeQuery) -> str:
        ...

    @abstractmethod
    def parse_response(self, doc: RawDocument) -> TradePage:
        ...


class ImportConnector(ABC):
    """Импорт без сети: CSV пользователя."""
    code: str = ""
    label: str = ""
