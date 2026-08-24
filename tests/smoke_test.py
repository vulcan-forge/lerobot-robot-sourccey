"""Installed-distribution smoke test used by release automation."""

from importlib.metadata import distribution
from importlib.resources import files

from lerobot.robots.config import RobotConfig
from lerobot.teleoperators.config import TeleoperatorConfig

import lerobot_robot_sourccey


metadata = distribution("lerobot_robot_sourccey").metadata
assert metadata["Name"].startswith("lerobot_robot_")
scripts = {
    entry.name: entry.value
    for entry in distribution("lerobot_robot_sourccey").entry_points
    if entry.group == "console_scripts"
}
assert scripts["sourccey-setup"] == "lerobot_robot_sourccey.setup:main"

assert RobotConfig.get_choice_class("sourccey") is lerobot_robot_sourccey.SourcceyConfig
assert RobotConfig.get_choice_class("sourccey_client") is lerobot_robot_sourccey.SourcceyClientConfig
assert TeleoperatorConfig.get_choice_class("sourccey_teleoperator") is (
    lerobot_robot_sourccey.SourcceyTeleoperatorConfig
)

package_root = files("lerobot_robot_sourccey")
assert package_root.joinpath("robots/sourccey/model/Arm.urdf").is_file()
assert package_root.joinpath(
    "robots/sourccey/defaults/left_arm_default_calibration.json"
).is_file()
assert package_root.joinpath("battery/golden/0100_2_01-bq34z100.srec").is_file()
