from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager import WebsocketRelayManager


def main() -> None:
    from .main import main as _main

    _main()


def __getattr__(name: str) -> Any:
    if name == "WebsocketRelayManager":
        from .manager import WebsocketRelayManager

        return WebsocketRelayManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["main", "WebsocketRelayManager"]

