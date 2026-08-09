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

import logging
import signal
import time

import zmq

from .config_sourccey import SourcceyConfig, SourcceyHostConfig
from .modules.host import silence_camera_warnings_for_host
from .modules.imu import IMUReporter
from .modules.relay import poll_relay, start_relay, stop_relay
from .sourccey import Sourccey

from ..protobuf.generated import sourccey_pb2


class SourcceyHost:
    def __init__(self, config: SourcceyHostConfig):
        self.zmq_context = zmq.Context()
        self.zmq_cmd_socket = self.zmq_context.socket(zmq.PULL)
        self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)
        self.zmq_cmd_socket.bind(f"tcp://*:{config.port_zmq_cmd}")

        self.zmq_observation_socket = self.zmq_context.socket(zmq.PUSH)
        self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)
        self.zmq_observation_socket.bind(f"tcp://*:{config.port_zmq_observations}")

        self.connection_time_s = config.connection_time_s
        self.watchdog_timeout_ms = config.watchdog_timeout_ms
        self.max_loop_freq_hz = config.max_loop_freq_hz

    def disconnect(self):
        self.zmq_observation_socket.close()
        self.zmq_cmd_socket.close()
        self.zmq_context.term()


def main():
    def _handle_termination_signal(signum, _frame):
        logging.info(f"Received signal {signum}. Shutting down Sourccey Host.")
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _handle_termination_signal)
    silence_camera_warnings_for_host()

    logging.info("Configuring Sourccey")
    robot_config = SourcceyConfig(id="sourccey")
    robot = Sourccey(robot_config)

    logging.info("Connecting Sourccey")
    robot.connect()
    # Establish a known-safe base state before accepting the first client command.
    robot.stop_base()

    logging.info("Starting Host")
    host_config = SourcceyHostConfig()
    host = SourcceyHost(host_config)
    imu_reporter = IMUReporter(host_config)
    imu_reporter.start()
    relay = start_relay(host_config)

    print("Waiting for commands...")

    # The watchdog is armed by the first valid command. Until then the base is
    # already stopped and an idle host should remain quietly ready for a client.
    last_cmd_time: float | None = None
    watchdog_active = False

    try:
        # Business logic
        start = time.perf_counter()
        duration = 0

        observation = None
        last_sent_camera_timestamps: dict[str, float | None] = {}
        while duration < host.connection_time_s:
            loop_start_time = time.time()
            poll_relay(relay)
            try:
                # Receive protobuf message instead of JSON
                msg_bytes = host.zmq_cmd_socket.recv(zmq.NOBLOCK)

                # Convert protobuf to action dictionary using existing method
                robot_action = sourccey_pb2.SourcceyRobotAction()
                robot_action.ParseFromString(msg_bytes)

                data = robot.protobuf_converter.protobuf_to_action(robot_action)

                # Send action to robot
                _action_sent = robot.send_action(data)

                # Update the robot
                robot.update()

                last_cmd_time = time.monotonic()
                watchdog_active = False
            except zmq.Again:
                if not watchdog_active:
                    # logging.warning("No command available")
                    pass
            except Exception as e:
                logging.error("Message fetching failed: %s", e)

            now = time.monotonic()
            if (
                last_cmd_time is not None
                and now - last_cmd_time > host.watchdog_timeout_ms / 1000
                and not watchdog_active
            ):
                logging.warning(
                    "Command not received for more than %d milliseconds. Stopping the base.",
                    host.watchdog_timeout_ms,
                )
                robot.stop_base()
                watchdog_active = True

            observation = robot.get_observation()

            # Send the observation to the remote agent
            try:
                if observation is not None and observation != {}:
                    current_camera_timestamps = {
                        cam_key: getattr(robot.cameras[cam_key], "latest_timestamp", None)
                        for cam_key in robot.cameras.keys()
                    }
                    has_new_camera_frame = (
                        len(current_camera_timestamps) == 0
                        or any(
                            timestamp is not None
                            and timestamp != last_sent_camera_timestamps.get(cam_key)
                            for cam_key, timestamp in current_camera_timestamps.items()
                        )
                    )
                    if not has_new_camera_frame:
                        logging.debug("Skipping observation send: no new camera frame timestamps.")
                        elapsed = time.time() - loop_start_time
                        time.sleep(max(1 / host.max_loop_freq_hz - elapsed, 0))
                        duration = time.perf_counter() - start
                        continue

                    # Convert observation to protobuf using existing method
                    robot_state = robot.protobuf_converter.observation_to_protobuf(observation)

                    # Send protobuf message instead of JSON
                    host.zmq_observation_socket.send(robot_state.SerializeToString(), flags=zmq.NOBLOCK)
                    last_sent_camera_timestamps = current_camera_timestamps
            except zmq.Again:
                logging.info("Dropping observation, no client connected")
            except Exception as e:
                logging.error(f"Failed to send observation: {e}")

            # Ensure a short sleep to avoid overloading the CPU.
            elapsed = time.time() - loop_start_time

            time.sleep(max(1 / host.max_loop_freq_hz - elapsed, 0))
            duration = time.perf_counter() - start
        print("Cycle time reached.")

    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting...")
    finally:
        print("Shutting down Sourccey Host.")
        stop_relay(relay)
        imu_reporter.stop()
        robot.disconnect()
        host.disconnect()

    logging.info("Finished Sourccey cleanly")


if __name__ == "__main__":
    main()
