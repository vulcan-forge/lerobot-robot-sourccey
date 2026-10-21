"""Sourccey session lifecycle around LeRobot's unmodified teleoperation loop."""

from contextlib import ExitStack

from lerobot.configs import parser
from lerobot.robots import Robot, make_robot_from_config
from lerobot.scripts.lerobot_teleoperate import TeleoperateConfig, teleop_loop
from lerobot.teleoperators import make_teleoperator_from_config
from lerobot.utils.import_utils import register_third_party_plugins
from lerobot.utils.utils import init_logging
from lerobot.utils.visualization_utils import init_visualization, shutdown_visualization

from .controls import make_control_processors


def disconnect_robot(robot: Robot) -> None:
    if robot.is_connected:
        robot.disconnect()


@parser.wrap()
def teleoperate(cfg: TeleoperateConfig) -> None:
    init_logging()
    teleop = make_teleoperator_from_config(cfg.teleop)
    robot = make_robot_from_config(cfg.robot)
    processors = make_control_processors(teleop, robot)
    with ExitStack() as resources:
        resources.callback(teleop.disconnect)
        teleop.connect()
        resources.callback(disconnect_robot, robot)
        robot.connect()
        if cfg.display_data:
            resources.callback(shutdown_visualization, cfg.display_mode)
            init_visualization(
                cfg.display_mode, session_name="teleoperation", ip=cfg.display_ip, port=cfg.display_port
            )
        try:
            teleop_loop(
                teleop=teleop,
                robot=robot,
                fps=cfg.fps,
                teleop_action_processor=processors[0],
                robot_action_processor=processors[1],
                robot_observation_processor=processors[2],
                duration=cfg.teleop_time_s,
                display_data=cfg.display_data,
                display_mode=cfg.display_mode,
                display_compressed_images=cfg.display_compressed_images
                or (cfg.display_data and cfg.display_ip is not None and cfg.display_port is not None),
            )
        except KeyboardInterrupt:
            pass


def main() -> None:
    register_third_party_plugins()
    teleoperate()


if __name__ == "__main__":
    main()
