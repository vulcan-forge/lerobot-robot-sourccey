import json

from lerobot_robot_sourccey.robots.sourccey.manual_drive import (
    ARM_POSITION_KEYS,
    ManualDriveBridge,
    ManualDrivePacket,
    _build_parser,
    parse_control_packet,
)


class FakeRobot:
    def __init__(self) -> None:
        self.speed_keys: list[str] = []
        self.base_keys: list[frozenset[str]] = []

    def on_key_down(self, key: str) -> None:
        self.speed_keys.append(key)

    def _from_keyboard_to_base_action(self, keys, z_position):
        pressed = frozenset(keys)
        self.base_keys.append(pressed)
        return {
            "x.vel": float("w" in pressed) - float("s" in pressed),
            "y.vel": float("a" in pressed) - float("d" in pressed),
            "theta.vel": float("z" in pressed) - float("x" in pressed),
            "z.pos": z_position if z_position is not None else 0.0,
            "untorque_left": False,
            "untorque_right": False,
        }


def packet_bytes(**overrides) -> bytes:
    value = {"nickname": "sourccey", "pressed_keys": ["w", "a"], "sent_at_ms": 1_000}
    value.update(overrides)
    return json.dumps(value).encode()


def test_parser_accepts_the_kiosk_packet_contract() -> None:
    packet = parse_control_packet(
        packet_bytes(nickname="@sourccey", pressed_keys=["W", " a ", "w"]),
        expected_nickname="sourccey",
        now_ms=1_100,
        max_age_ms=500,
    )

    assert packet == ManualDrivePacket("sourccey", frozenset({"w", "a"}), 1_000)


def test_parser_rejects_stale_wrong_robot_and_unknown_keys() -> None:
    common = {"expected_nickname": "sourccey", "now_ms": 2_000, "max_age_ms": 500}

    assert parse_control_packet(packet_bytes(), **common) is None
    assert parse_control_packet(packet_bytes(nickname="other", sent_at_ms=2_000), **common) is None
    assert parse_control_packet(packet_bytes(pressed_keys=["space"], sent_at_ms=2_000), **common) is None


def test_bridge_holds_arms_and_stops_after_command_timeout() -> None:
    now = [5.0]
    robot = FakeRobot()
    bridge = ManualDriveBridge(robot, "sourccey", command_timeout_ms=500, monotonic=lambda: now[0])
    observation = {key: float(index) for index, key in enumerate(ARM_POSITION_KEYS)}
    observation["z.pos"] = 12.5
    bridge.accept(ManualDrivePacket("sourccey", frozenset({"w", "a"}), 0))

    moving = bridge.build_action(observation)
    now[0] = 5.6
    stopped = bridge.build_action({})

    assert moving is not None and moving["x.vel"] == 1.0 and moving["y.vel"] == 1.0
    assert stopped is not None and stopped["x.vel"] == 0.0 and stopped["y.vel"] == 0.0
    assert all(stopped[key] == observation[key] for key in ARM_POSITION_KEYS)


def test_speed_keys_are_edge_triggered() -> None:
    robot = FakeRobot()
    bridge = ManualDriveBridge(robot, "sourccey", monotonic=lambda: 1.0)
    observation = {key: 0.0 for key in ARM_POSITION_KEYS}
    packet = ManualDrivePacket("sourccey", frozenset({"r"}), 0)

    bridge.accept(packet)
    bridge.build_action(observation)
    bridge.accept(packet)
    bridge.build_action(observation)

    assert robot.speed_keys == ["r"]


def test_cli_accepts_existing_kiosk_argument_names() -> None:
    args = _build_parser().parse_args(
        ["--id=sourccey", "--remote_ip=127.0.0.1", "--udp_port=5561", "--fps=30"]
    )

    assert args.id == "sourccey"
    assert args.remote_ip == "127.0.0.1"
    assert args.udp_port == 5561
    assert args.fps == 30.0
