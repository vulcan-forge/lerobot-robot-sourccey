"""Kiosk-controlled manual driving for Sourccey.

The kiosk sends small JSON datagrams containing its current pressed-key set.
This process translates those keys into normal ``SourcceyClient`` actions so
manual driving uses the same velocity, lift, and speed behavior as keyboard
teleoperation.
"""

from __future__ import annotations

import argparse
import json
import signal
import socket
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .config_sourccey import SourcceyClientConfig
from .sourccey_client import SourcceyClient


DEFAULT_UDP_HOST = "127.0.0.1"
DEFAULT_UDP_PORT = 5561
DEFAULT_FPS = 30.0
DEFAULT_COMMAND_TIMEOUT_MS = 500
ALLOWED_KEYS = frozenset({"w", "a", "s", "d", "z", "x", "q", "e", "r", "f"})
ARM_POSITION_KEYS = tuple(
    f"{side}_{joint}.pos"
    for side in ("left", "right")
    for joint in (
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    )
)


@dataclass(frozen=True)
class ManualDrivePacket:
    nickname: str
    pressed_keys: frozenset[str]
    sent_at_ms: int


def normalize_nickname(value: str) -> str:
    return value.strip().lstrip("@").strip()


def parse_control_packet(
    payload: bytes,
    *,
    expected_nickname: str,
    now_ms: int,
    max_age_ms: int,
) -> ManualDrivePacket | None:
    """Validate a kiosk datagram, returning ``None`` for unsafe input."""
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None

    nickname = value.get("nickname")
    keys = value.get("pressed_keys")
    sent_at_ms = value.get("sent_at_ms")
    if not isinstance(nickname, str) or not isinstance(keys, list):
        return None
    if isinstance(sent_at_ms, bool) or not isinstance(sent_at_ms, int):
        return None
    if normalize_nickname(nickname) != normalize_nickname(expected_nickname):
        return None
    if sent_at_ms > now_ms + max_age_ms or now_ms - sent_at_ms > max_age_ms:
        return None
    if any(not isinstance(key, str) for key in keys):
        return None

    normalized_keys = frozenset(key.strip().lower() for key in keys)
    if not normalized_keys <= ALLOWED_KEYS:
        return None
    return ManualDrivePacket(normalize_nickname(nickname), normalized_keys, sent_at_ms)


class ManualDriveBridge:
    """Maintain kiosk key state and build safe, complete robot actions."""

    def __init__(
        self,
        robot: SourcceyClient,
        nickname: str,
        *,
        command_timeout_ms: int = DEFAULT_COMMAND_TIMEOUT_MS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.robot = robot
        self.nickname = normalize_nickname(nickname)
        self.command_timeout_s = command_timeout_ms / 1000.0
        self._monotonic = monotonic
        self._pressed_keys: frozenset[str] = frozenset()
        self._previous_keys: frozenset[str] = frozenset()
        self._last_packet_at: float | None = None
        self._arm_hold: dict[str, float] = {}

    def accept(self, packet: ManualDrivePacket) -> None:
        self._pressed_keys = packet.pressed_keys
        self._last_packet_at = self._monotonic()

    def current_keys(self) -> frozenset[str]:
        if self._last_packet_at is None:
            return frozenset()
        if self._monotonic() - self._last_packet_at > self.command_timeout_s:
            return frozenset()
        return self._pressed_keys

    def build_action(self, observation: dict[str, Any]) -> dict[str, float | bool] | None:
        for key in ARM_POSITION_KEYS:
            value = observation.get(key)
            if isinstance(value, (int, float)):
                self._arm_hold[key] = float(value)
        if len(self._arm_hold) != len(ARM_POSITION_KEYS):
            return None

        keys = self.current_keys()
        for speed_key in ("r", "f"):
            if speed_key in keys and speed_key not in self._previous_keys:
                self.robot.on_key_down(speed_key)

        z_position = observation.get("z.pos")
        base_action = self.robot._from_keyboard_to_base_action(  # noqa: SLF001
            list(keys),
            float(z_position) if isinstance(z_position, (int, float)) else None,
        )
        self._previous_keys = keys
        return {**self._arm_hold, **base_action}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bridge Sourccey kiosk manual-drive UDP controls to the robot host."
    )
    parser.add_argument("--id", default="sourccey", help="Robot nickname expected in kiosk packets.")
    parser.add_argument(
        "--remote-ip",
        "--remote_ip",
        dest="remote_ip",
        default="127.0.0.1",
        help="IP address of the running sourccey-host process.",
    )
    parser.add_argument(
        "--udp-host",
        default=DEFAULT_UDP_HOST,
        help="Local interface on which kiosk control datagrams are received.",
    )
    parser.add_argument(
        "--udp-port",
        "--udp_port",
        dest="udp_port",
        type=int,
        default=DEFAULT_UDP_PORT,
        help="Local UDP port for kiosk control datagrams.",
    )
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS, help="Robot command rate.")
    parser.add_argument(
        "--command-timeout-ms",
        type=int,
        default=DEFAULT_COMMAND_TIMEOUT_MS,
        help="Stop motion when kiosk controls have not refreshed within this interval.",
    )
    return parser


def run_manual_drive(args: argparse.Namespace) -> None:
    if not 1 <= args.udp_port <= 65535:
        raise ValueError("udp_port must be between 1 and 65535")
    if args.fps <= 0:
        raise ValueError("fps must be positive")
    if args.command_timeout_ms <= 0:
        raise ValueError("command_timeout_ms must be positive")
    nickname = normalize_nickname(args.id)
    if not nickname:
        raise ValueError("id must not be empty")

    robot = SourcceyClient(
        SourcceyClientConfig(
            id=nickname,
            remote_ip=args.remote_ip,
            cameras={},
            log_no_data_timeouts=False,
        )
    )
    bridge = ManualDriveBridge(robot, nickname, command_timeout_ms=args.command_timeout_ms)
    control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control_socket.bind((args.udp_host, args.udp_port))
    control_socket.setblocking(False)
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous_handlers: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, request_stop)

    print(
        f"Manual drive listening on udp://{args.udp_host}:{args.udp_port} "
        f"for {nickname}; robot host={args.remote_ip}",
        flush=True,
    )
    try:
        robot.connect()
        interval = 1.0 / args.fps
        while not stopping:
            loop_started = time.monotonic()
            while True:
                try:
                    payload, _address = control_socket.recvfrom(65535)
                except BlockingIOError:
                    break
                packet = parse_control_packet(
                    payload,
                    expected_nickname=nickname,
                    now_ms=time.time_ns() // 1_000_000,
                    max_age_ms=args.command_timeout_ms,
                )
                if packet is not None:
                    bridge.accept(packet)

            observation = robot.get_observation()
            action = bridge.build_action(observation)
            if action is not None:
                robot.send_action(action)

            remaining = interval - (time.monotonic() - loop_started)
            if remaining > 0:
                time.sleep(remaining)
    finally:
        control_socket.close()
        if robot.is_connected:
            # disconnect() sends a best-effort zero-velocity action before closing.
            robot.disconnect()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main(argv: Sequence[str] | None = None) -> None:
    run_manual_drive(_build_parser().parse_args(argv))


if __name__ == "__main__":
    main()
