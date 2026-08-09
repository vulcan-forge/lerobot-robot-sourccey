# Copyright 2025 The HuggingFace Inc. team. All rights reserved.
# Copyright 2025 Vulcan Robotics, Inc. All rights reserved.
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

from dataclasses import dataclass


@dataclass
class SlamInputConfig:
    """Configuration for Sourccey -> SLAM sidecar publishing."""

    input_enabled: bool = False
    input_endpoint: str = "tcp://127.0.0.1:5560"
    stereo_left_key: str = "front_left"
    stereo_right_key: str = "front_right"
    jpeg_quality: int = 80

