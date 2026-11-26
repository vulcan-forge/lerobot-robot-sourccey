# Copyright 2026 Vulcan Robotics, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Sourccey keyboard mapping for LeRobot's composite teleoperator.

Select it with ``--teleop.type=composite --teleop.base.type=keyboard
--teleop.mapping.type=sourccey_keyboard``. On top of LeRobot's planar base
mapping it drives the lift (``z.pos``) and toggles per-arm untorque.
"""

import math
import time
from dataclasses import dataclass, field
from typing import Any

from lerobot.configs import FeatureType, PipelineFeatureType, PolicyFeature
from lerobot.lerobot_types import RobotAction, TransitionKey
from lerobot.processor.base_action_processor import BaseActionProcessorStep
from lerobot.processor.keyboard_base_processor import (
    KeyboardToBaseActionProcessorStep,
    default_base_key_bindings,
)
from lerobot.processor.pipeline import ProcessorStepRegistry

Z_MIN = -100.0
Z_MAX = 100.0


def sourccey_key_bindings(layout: str = "qwerty") -> dict[str, str]:
    """Add lift and untorque keys at the physical positions of QWERTY Q/E and N/M."""
    return {
        **default_base_key_bindings(layout),
        "lift_up": "a" if layout == "azerty" else "q",
        "lift_down": "e",
        "untorque_left": "n",
        "untorque_right": "," if layout == "azerty" else "m",
    }


@BaseActionProcessorStep.register_subclass("sourccey_keyboard")
@ProcessorStepRegistry.register("sourccey_keyboard_to_base_action")
@dataclass
class SourcceyKeyboardToBaseActionProcessorStep(KeyboardToBaseActionProcessorStep):
    """Keyboard mapping for Sourccey's mecanum base, lift, and arm untorque toggles.

    Sourccey base velocities are normalized to [-1, 1], so the speed presets are
    normalized values rather than m/s and deg/s. Holding a lift key moves the
    ``z.pos`` target, which starts at the measured lift position. Untorque keys
    toggle on each press.
    """

    linear_speeds: tuple[float, ...] = (0.8, 0.9, 1.0)
    angular_speeds: tuple[float, ...] = (0.8, 0.9, 1.0)
    # z.pos units per second while a lift key is held: full travel in 8 s.
    lift_speed: float = (Z_MAX - Z_MIN) / 8.0
    # Upper bound on one target step, so a stalled loop does not jump the lift.
    lift_max_step: float = 2.0
    _z_target: float | None = field(default=None, init=False, repr=False)
    _last_time: float | None = field(default=None, init=False, repr=False)
    _untorque: dict[str, bool] = field(
        default_factory=lambda: {"untorque_left": False, "untorque_right": False}, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.key_bindings is None:
            self.key_bindings = sourccey_key_bindings(self.layout)
        super().__post_init__()
        missing = sourccey_key_bindings().keys() - self.key_bindings.keys()
        if missing:
            raise ValueError(f"Missing keyboard bindings: {sorted(missing)}")
        values = list(self.key_bindings.values())
        if len(values) != len(set(values)):
            raise ValueError(f"Keyboard bindings must use distinct keys: {self.key_bindings}")

    def action(self, action: RobotAction) -> RobotAction:
        # The parent updates the pressed-key state, so read the previous state first.
        pressed = {key for key, value in action.items() if value is None}
        newly_pressed = pressed - self._pressed
        mapped = super().action(action)
        keys = self.key_bindings
        assert keys is not None

        now = time.monotonic()
        dt = 0.0 if self._last_time is None else now - self._last_time
        self._last_time = now

        if self._z_target is None:
            observation = self.transition.get(TransitionKey.OBSERVATION) or {}
            measured = observation.get("z.pos")
            if measured is not None and math.isfinite(measured) and Z_MIN <= measured <= Z_MAX:
                self._z_target = float(measured)
        direction = int(keys["lift_up"] in pressed) - int(keys["lift_down"] in pressed)
        if self._z_target is not None:
            step = max(-self.lift_max_step, min(direction * self.lift_speed * dt, self.lift_max_step))
            self._z_target = max(Z_MIN, min(self._z_target + step, Z_MAX))
            mapped["z.pos"] = self._z_target
        # Without a valid measurement, z.pos stays out and the hold step keeps the lift in place.

        for name in self._untorque:
            if keys[name] in newly_pressed:
                self._untorque[name] = not self._untorque[name]
            mapped[name] = self._untorque[name]
        return mapped

    def reset(self) -> None:
        super().reset()
        self._z_target = None
        self._last_time = None
        self._untorque = dict.fromkeys(self._untorque, False)

    def get_config(self) -> dict[str, Any]:
        return {**super().get_config(), "lift_speed": self.lift_speed, "lift_max_step": self.lift_max_step}

    def transform_features(
        self, features: dict[PipelineFeatureType, dict[str, PolicyFeature]]
    ) -> dict[PipelineFeatureType, dict[str, PolicyFeature]]:
        features = super().transform_features(features)
        features[PipelineFeatureType.ACTION]["z.pos"] = PolicyFeature(type=FeatureType.ACTION, shape=(1,))
        return features
