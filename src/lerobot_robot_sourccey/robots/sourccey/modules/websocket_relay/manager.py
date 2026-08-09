from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlparse

import websockets

from .bridge import WebsocketRelayBridge
from .config import NoActiveRobotSessionError, WebsocketRelayConfig

INITIAL_CONNECT_RETRY_DELAY_S = 15.0
SESSION_RECOVERY_RETRY_DELAY_S = 15.0
SESSION_RECOVERY_CLOSE_REASONS = {"session_not_found"}


def _emit(message: str) -> None:
    print(message)
    logging.info(message)


class HostWebsocketRelayConfig(Protocol):
    websocket_relay_autostart: bool
    websocket_relay_forward_observations: bool


class WebsocketRelayManager:
    def __init__(self, config: HostWebsocketRelayConfig):
        self.config = config
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started = False
        self._force_autostart = False

    def set_force_autostart(self, force: bool) -> None:
        self._force_autostart = force

    def _should_autostart(self) -> bool:
        return self.config.websocket_relay_autostart or self._force_autostart

    def start_if_configured(self) -> bool:
        if not self._should_autostart():
            logging.info("Websocket relay autostart disabled.")
            return False

        mode = "full_bridge" if self.config.websocket_relay_forward_observations else "commands_only"
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] websocket_relay.autostart_enabled "
            f"mode={mode}"
        )
        logging.info("Websocket relay autostart enabled (mode=%s).", mode)
        try:
            self.start()
            return True
        except Exception as exc:  # noqa: BLE001
            logging.warning("Websocket relay failed to start (continuing without relay): %s", exc)
            return False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
            name="sourccey_websocket_relay",
        )
        self._thread.start()
        self._started = True

    def poll(self) -> None:
        try:
            if not self._should_autostart():
                return
            if self._thread is not None and self._thread.is_alive():
                return
            if not self._started:
                return
            self.start()
        except Exception as exc:  # noqa: BLE001
            logging.warning("Websocket relay poll failed (continuing host loop): %s", exc)

    def stop(self) -> None:
        try:
            self._stop_event.set()
            thread = self._thread
            self._thread = None
            if thread is not None:
                thread.join(timeout=3.0)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Websocket relay stop failed: %s", exc)

    def _thread_main(self) -> None:
        def _utc_now() -> str:
            return datetime.now(timezone.utc).isoformat()

        _emit(f"[{_utc_now()}] websocket_relay.thread_started")

        def _redact_ws_url(ws_url: str) -> str:
            token_marker = "token="
            token_idx = ws_url.find(token_marker)
            if token_idx == -1:
                return ws_url
            token_start = token_idx + len(token_marker)
            token_end = ws_url.find("&", token_start)
            if token_end == -1:
                token_end = len(ws_url)
            visible = ws_url[token_start : min(token_start + 4, token_end)]
            return f"{ws_url[:token_start]}{visible}...redacted{ws_url[token_end:]}"

        async def _runner() -> None:
            mode = "full_bridge" if self.config.websocket_relay_forward_observations else "commands_only"
            waiting_for_session_logged = False
            connecting_logged = False
            localhost_warning_logged = False
            logged_connected_session_id: str | None = None
            connected_once = False
            stale_session_wait_logged_for: str | None = None

            while not self._stop_event.is_set():
                try:
                    cfg = WebsocketRelayConfig.from_env()
                    waiting_for_session_logged = False
                except NoActiveRobotSessionError as exc:
                    stale_session_wait_logged_for = None
                    logged_connected_session_id = None
                    if not waiting_for_session_logged:
                        _emit(
                            f"[{_utc_now()}] websocket_relay.waiting_for_active_session "
                            f"reason={exc}"
                        )
                        waiting_for_session_logged = True
                    await asyncio.sleep(2.0)
                    continue
                except Exception as exc:  # noqa: BLE001
                    waiting_for_session_logged = False
                    stale_session_wait_logged_for = None
                    logged_connected_session_id = None
                    # Startup/session discovery can fail transiently when the host is
                    # launched manually before the cloud relay is ready. Keep those
                    # retries silent until we have established a real relay session.
                    if connected_once:
                        _emit(
                            f"[{_utc_now()}] websocket_relay.config_failed "
                            f"error_type={type(exc).__name__} error={exc!r}"
                        )
                    await asyncio.sleep(2.0)
                    continue

                if stale_session_wait_logged_for != cfg.websocket_relay_session_id:
                    stale_session_wait_logged_for = None

                if is_localhost_ws_url(cfg.websocket_relay_ws_base_url) and not localhost_warning_logged:
                    _emit(
                        f"[{_utc_now()}] websocket_relay.warn using localhost relay base URL "
                        f"({cfg.websocket_relay_ws_base_url}). If relay runs on another host, "
                        "set VULCAN_WEBSOCKET_RELAY_WS_BASE_URL (or legacy "
                        "VULCAN_RELAY_WS_BASE_URL) to that host/IP."
                    )
                    localhost_warning_logged = True

                redacted_ws_url = _redact_ws_url(cfg.ws_url)

                def _on_connected(active_cfg: WebsocketRelayConfig) -> None:
                    nonlocal connected_once, logged_connected_session_id
                    if logged_connected_session_id == active_cfg.websocket_relay_session_id:
                        return
                    _emit(
                        f"[{_utc_now()}] websocket_relay.connected "
                        f"session_id={active_cfg.websocket_relay_session_id} "
                        f"robot_id={active_cfg.robot_id}"
                    )
                    connected_once = True
                    logged_connected_session_id = active_cfg.websocket_relay_session_id

                bridge = WebsocketRelayBridge(
                    cfg,
                    forward_observations=self.config.websocket_relay_forward_observations,
                    forward_commands=True,
                    on_connected=_on_connected,
                )
                try:
                    if not connecting_logged:
                        _emit(
                            f"[{_utc_now()}] websocket_relay.connecting "
                            f"mode={mode} ws_url={redacted_ws_url} "
                            f"retry_in_s={INITIAL_CONNECT_RETRY_DELAY_S:.1f} "
                            "retry_logging=silent_until_connected"
                        )
                        connecting_logged = True
                    await bridge.run_forever()
                except websockets.ConnectionClosed as exc:
                    retry_delay_s = _disconnect_retry_delay(exc)
                    if _is_stale_session_disconnect(exc):
                        stale_session_wait_logged_for = cfg.websocket_relay_session_id
                    else:
                        stale_session_wait_logged_for = None
                        _emit(
                            f"[{_utc_now()}] websocket_relay.disconnected "
                            f"session_id={cfg.websocket_relay_session_id} "
                            f"robot_id={cfg.robot_id} "
                            f"code={exc.code} reason={exc.reason or 'none'} reconnect_in_s={retry_delay_s:.1f}"
                        )
                    if self._stop_event.is_set():
                        break
                    await asyncio.sleep(retry_delay_s)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    stale_session_wait_logged_for = None
                    if self._stop_event.is_set():
                        break
                    await asyncio.sleep(INITIAL_CONNECT_RETRY_DELAY_S)
                finally:
                    await bridge.close()

        try:
            asyncio.run(_runner())
        except Exception as exc:  # noqa: BLE001
            _emit(
                f"[{_utc_now()}] websocket_relay.thread_failed "
                f"error_type={type(exc).__name__} error={exc!r}"
            )
            logging.warning("Websocket relay thread exited: %s", exc)


def is_localhost_ws_url(ws_base_url: str) -> bool:
    try:
        host = (urlparse(ws_base_url).hostname or "").strip().lower()
    except Exception:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _disconnect_reason(exc: websockets.ConnectionClosed) -> str:
    return (exc.reason or "").strip().lower()


def _is_stale_session_disconnect(exc: websockets.ConnectionClosed) -> bool:
    return exc.code == 1008 and _disconnect_reason(exc) in SESSION_RECOVERY_CLOSE_REASONS


def _disconnect_retry_delay(exc: websockets.ConnectionClosed) -> float:
    if _is_stale_session_disconnect(exc):
        return SESSION_RECOVERY_RETRY_DELAY_S
    return 1.0

