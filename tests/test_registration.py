from lerobot.robots.config import RobotConfig
from lerobot.teleoperators.config import TeleoperatorConfig

import lerobot_robot_sourccey


def test_plugin_registers_sourccey_devices() -> None:
    assert RobotConfig.get_choice_class("sourccey") is lerobot_robot_sourccey.SourcceyConfig
    assert RobotConfig.get_choice_class("sourccey_client") is lerobot_robot_sourccey.SourcceyClientConfig
    assert RobotConfig.get_choice_class("sourccey_follower") is lerobot_robot_sourccey.SourcceyFollowerConfig
    assert TeleoperatorConfig.get_choice_class("sourccey_leader") is lerobot_robot_sourccey.SourcceyLeaderConfig
    assert (
        TeleoperatorConfig.get_choice_class("bi_sourccey_leader")
        is lerobot_robot_sourccey.BiSourcceyLeaderConfig
    )


def test_device_names_match_config_names() -> None:
    pairs = (
        (lerobot_robot_sourccey.SourcceyConfig, lerobot_robot_sourccey.Sourccey),
        (lerobot_robot_sourccey.SourcceyClientConfig, lerobot_robot_sourccey.SourcceyClient),
        (lerobot_robot_sourccey.SourcceyFollowerConfig, lerobot_robot_sourccey.SourcceyFollower),
        (lerobot_robot_sourccey.SourcceyLeaderConfig, lerobot_robot_sourccey.SourcceyLeader),
        (lerobot_robot_sourccey.BiSourcceyLeaderConfig, lerobot_robot_sourccey.BiSourcceyLeader),
    )

    for config_class, device_class in pairs:
        assert device_class.__name__ == config_class.__name__.removesuffix("Config")
