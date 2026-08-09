from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from urllib.parse import urlparse

import websockets

from .bridge import WebsocketRelayBridge
from .config import WebsocketRelayConfig


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Sourccey websocket relay.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Validate config and print websocket URL, then exit.",
    )
    parser.add_argument(
        "--ws-only",
        action="store_true",
        help="Run websocket probe mode only (no ZMQ bridge).",
    )
    parser.add_argument(
        "--commands-only",
        action="store_true",
        help="Run relay bridge with command forwarding only (disable observation uplink).",
    )
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _is_localhost_ws_url(ws_base_url: str) -> bool:
    try:
        host = (urlparse(ws_base_url).hostname or "").strip().lower()
    except Exception:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


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


def _summarize_ws_message(raw_message: str | bytes) -> str:
    if isinstance(raw_message, bytes):
        return f"bytes={len(raw_message)}"

    try:
        parsed = json.loads(raw_message)
    except json.JSONDecodeError:
        snippet = raw_message[:160].replace("\n", " ")
        return f"text_len={len(raw_message)} snippet={snippet!r}"

    if isinstance(parsed, dict):
        message_type = str(parsed.get("type", "unknown")).strip() or "unknown"
        return f"type={message_type}"

    return f"json_type={type(parsed).__name__}"


async def _run_ws_probe(cfg: WebsocketRelayConfig) -> None:
    backoff_s = cfg.connect_retry_backoff_s
    max_backoff_s = max(cfg.connect_retry_backoff_s, cfg.connect_retry_max_backoff_s)
    ping_interval = cfg.websocket_ping_interval_s if cfg.websocket_ping_interval_s > 0 else None
    ping_timeout = cfg.websocket_ping_timeout_s if cfg.websocket_ping_timeout_s > 0 else None
    redacted_ws_url = _redact_ws_url(cfg.ws_url)

    while True:
        ws = None
        try:
            print(f"[{_utc_now()}] websocket_relay.ws_probe_connecting ws_url={redacted_ws_url}")
            ws = await websockets.connect(
                cfg.ws_url,
                max_size=2**22,
                ping_interval=ping_interval,
                ping_timeout=ping_timeout,
            )
            print(
                f"[{_utc_now()}] websocket_relay.ws_probe_connected "
                f"session_id={cfg.websocket_relay_session_id} robot_id={cfg.robot_id}"
            )

            async def _heartbeat_loop() -> None:
                while True:
                    await asyncio.sleep(cfg.heartbeat_seconds)
                    assert ws is not None
                    await ws.send('{"type":"heartbeat"}')
                    print(f"[{_utc_now()}] websocket_relay.ws_probe_heartbeat_sent")

            async def _receive_loop() -> None:
                assert ws is not None
                async for raw_message in ws:
                    print(
                        f"[{_utc_now()}] websocket_relay.ws_probe_message_in "
                        f"{_summarize_ws_message(raw_message)}"
                    )

            await asyncio.gather(_heartbeat_loop(), _receive_loop())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            error_type = type(exc).__name__
            error_traceback = traceback.format_exc()
            print(
                f"[{_utc_now()}] websocket_relay.ws_probe_failed "
                f"retry_in_s={backoff_s:.1f} error_type={error_type} error={exc!r}"
            )
            print(f"[{_utc_now()}] websocket_relay.ws_probe_failed_traceback\n{error_traceback}")
            await asyncio.sleep(backoff_s)
            backoff_s = min(max_backoff_s, backoff_s * 2.0)
        finally:
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass


def main() -> None:
    args = _parse_args()
    if args.ws_only and args.commands_only:
        raise SystemExit("--ws-only and --commands-only are mutually exclusive.")

    cfg = WebsocketRelayConfig.from_env()
    redacted_ws_url = _redact_ws_url(cfg.ws_url)

    if args.once:
        print(f"websocket_relay.ready=true ws_url={redacted_ws_url}")
        return

    if _is_localhost_ws_url(cfg.websocket_relay_ws_base_url):
        print(
            f"[{_utc_now()}] websocket_relay.warn using localhost relay base URL "
            f"({cfg.websocket_relay_ws_base_url}). If relay runs on another host, set "
            "VULCAN_WEBSOCKET_RELAY_WS_BASE_URL (or legacy VULCAN_RELAY_WS_BASE_URL) to that host/IP."
        )

    async def _runner() -> None:
        backoff_s = cfg.connect_retry_backoff_s
        max_backoff_s = max(cfg.connect_retry_backoff_s, cfg.connect_retry_max_backoff_s)
        while True:
            bridge = WebsocketRelayBridge(
                cfg,
                forward_observations=not args.commands_only,
                forward_commands=True,
            )
            try:
                mode = "commands_only" if args.commands_only else "full_bridge"
                print(f"[{_utc_now()}] websocket_relay.connecting mode={mode} ws_url={redacted_ws_url}")
                await bridge.run_forever()
            except websockets.ConnectionClosed as exc:
                print(
                    f"[{_utc_now()}] websocket_relay.disconnected "
                    f"session_id={cfg.websocket_relay_session_id} "
                    f"robot_id={cfg.robot_id} "
                    f"code={exc.code} reason={exc.reason or 'none'} reconnect_in_s=1.0"
                )
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[{_utc_now()}] websocket_relay.connect_failed "
                    f"retry_in_s={backoff_s:.1f} error_type={type(exc).__name__} error={exc!r}"
                )
                await asyncio.sleep(backoff_s)
                backoff_s = min(max_backoff_s, backoff_s * 2.0)
            else:
                # Unexpected normal exit; reconnect defensively after short delay.
                await asyncio.sleep(1.0)
            finally:
                await bridge.close()

    if args.ws_only:
        asyncio.run(_run_ws_probe(cfg))
        return

    asyncio.run(_runner())


if __name__ == "__main__":
    main()

