import argparse
import sys

from ...config_sourccey import SourcceyConfig
from ...sourccey import Sourccey


def _resolve_target_arms(args: argparse.Namespace) -> tuple[bool, bool]:
    use_left = args.left or not args.right
    use_right = args.right or not args.left
    return use_left, use_right


def _set_bus_torque_best_effort(bus, *, enable: bool, arm_label: str) -> tuple[list[str], list[str]]:
    connected_motors: list[str] = []
    failed_motors: list[str] = []
    action = "enable" if enable else "disable"

    try:
        bus.connect(handshake=False)
    except Exception as exc:
        return [], [f"{arm_label} arm bus open failed: {exc}"]

    try:
        for motor_name in bus.motors:
            try:
                if enable:
                    bus.enable_torque(motor_name, num_retry=1)
                else:
                    bus.disable_torque(motor_name, num_retry=1)
                connected_motors.append(motor_name)
            except Exception as exc:
                failed_motors.append(f"{arm_label}:{motor_name} {action} failed: {exc}")
    finally:
        try:
            bus.disconnect(disable_torque=False)
        except Exception as exc:
            failed_motors.append(f"{arm_label} arm disconnect failed: {exc}")

    return connected_motors, failed_motors


def main() -> None:
    parser = argparse.ArgumentParser(description="Toggle Sourccey arm torque.")
    parser.add_argument("--id", default="sourccey", help="Robot id to use when constructing the Sourccey config.")
    parser.add_argument("--left", action="store_true", help="Only affect the left arm.")
    parser.add_argument("--right", action="store_true", help="Only affect the right arm.")
    parser.add_argument("--enable", action="store_true", help="Enable torque instead of disabling it.")
    parser.add_argument("--left-arm-port", default=None, help="Override left arm serial port.")
    parser.add_argument("--right-arm-port", default=None, help="Override right arm serial port.")
    args = parser.parse_args()

    use_left, use_right = _resolve_target_arms(args)

    config = SourcceyConfig(id=args.id)
    if args.left_arm_port:
        config.left_arm_port = args.left_arm_port
    if args.right_arm_port:
        config.right_arm_port = args.right_arm_port

    robot = Sourccey(config)
    succeeded: list[str] = []
    failures: list[str] = []

    if use_left:
        left_success, left_failures = _set_bus_torque_best_effort(robot.left_arm.bus, enable=args.enable, arm_label="left")
        succeeded.extend(f"left:{motor}" for motor in left_success)
        failures.extend(left_failures)

    if use_right:
        right_success, right_failures = _set_bus_torque_best_effort(
            robot.right_arm.bus, enable=args.enable, arm_label="right"
        )
        succeeded.extend(f"right:{motor}" for motor in right_success)
        failures.extend(right_failures)

    if succeeded:
        action_word = "Enabled" if args.enable else "Disabled"
        print(f"{action_word} torque on motors: {', '.join(succeeded)}")

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)

    if not succeeded:
        raise SystemExit("Failed to reach any requested motors.")

    if failures:
        raise SystemExit("Untorque incomplete. Check logs for unreachable motors.")


if __name__ == "__main__":
    main()
