from types import SimpleNamespace
from unittest.mock import Mock
from threading import Event, Thread

import numpy as np
import pytest
import zmq

from lerobot_robot_sourccey.robots.protobuf.generated import sourccey_pb2
from lerobot_robot_sourccey.robots.protobuf.sourccey_protobuf import SourcceyProtobuf
from lerobot_robot_sourccey.robots.sourccey import sourccey_host
from lerobot_robot_sourccey.robots.sourccey.sourccey import Sourccey
from lerobot_robot_sourccey.robots.sourccey.config_sourccey import SourcceyClientConfig
from lerobot_robot_sourccey.robots.sourccey.sourccey_client import SourcceyClient


@pytest.mark.parametrize("camera", [SimpleNamespace(), SimpleNamespace(latest_timestamp=None),
                                         SimpleNamespace(latest_timestamp=1.0)])
def test_host_publishes_state_and_frames_without_fresh_timestamps(monkeypatch, camera):
    robot = Mock()
    robot.cameras = {"front_left": camera}
    robot.protobuf_converter = SourcceyProtobuf()
    robot.get_observation.return_value = {
        "z.pos": 12.0,
        "front_left": np.full((24, 32, 3), 100, dtype=np.uint8),
    }
    host = Mock(connection_time_s=3, watchdog_timeout_ms=500, max_loop_freq_hz=30)
    host.zmq_cmd_socket.recv.side_effect = zmq.Again()
    monkeypatch.setattr(sourccey_host, "Sourccey", lambda config: robot)
    monkeypatch.setattr(sourccey_host, "SourcceyHost", lambda config: host)
    monkeypatch.setattr(sourccey_host, "IMUReporter", Mock())
    for name in ("silence_camera_warnings_for_host", "start_relay", "poll_relay", "stop_relay"):
        monkeypatch.setattr(sourccey_host, name, Mock())
    monkeypatch.setattr(sourccey_host.signal, "signal", Mock())
    monkeypatch.setattr(sourccey_host.time, "sleep", Mock())
    ticks = iter([0, 1, 2, 3])
    monkeypatch.setattr(sourccey_host.time, "perf_counter", lambda: next(ticks))

    sourccey_host.main()

    assert host.zmq_observation_socket.send.call_count == 3
    for call in host.zmq_observation_socket.send.call_args_list:
        state = sourccey_pb2.SourcceyRobotState.FromString(call.args[0])
        observation = robot.protobuf_converter.protobuf_to_observation(state)
        assert observation["z.pos"] == 12.0
        assert observation["front_left"].shape == (24, 32, 3)
    robot.send_action.assert_not_called()
    robot.stop_base.assert_called_once()
    robot.disconnect.assert_called_once()


@pytest.mark.parametrize("api", ["read_latest", "async_read"])
def test_camera_read_supports_both_lerobot_apis(api):
    robot = object.__new__(Sourccey)
    frame = np.ones((24, 32, 3), dtype=np.uint8)
    reader = Mock(return_value=frame)
    robot.cameras = {"front_left": SimpleNamespace(**{api: reader})}
    assert robot._read_camera("front_left") is frame
    reader.assert_called_once_with(**({"timeout_ms": 50} if api == "async_read" else {}))


@pytest.mark.parametrize("camera", [SimpleNamespace(), SimpleNamespace(async_read=Mock(side_effect=TimeoutError))])
def test_failed_camera_returns_placeholder_instead_of_discarding_state(camera):
    robot = object.__new__(Sourccey)
    robot.cameras = {"front_left": camera}
    robot.config = SimpleNamespace(cameras={"front_left": SimpleNamespace(height=24, width=32)})
    frame = robot._read_camera("front_left")
    assert frame.shape == (24, 32, 3)
    assert not frame.any()


def test_client_connects_to_real_host_socket_with_camera_observation(tmp_path):
    host = sourccey_host.SourcceyHost(SimpleNamespace(
        port_zmq_cmd="*", port_zmq_observations="*", connection_time_s=10,
        watchdog_timeout_ms=500, max_loop_freq_hz=30,
    ))
    for socket in (host.zmq_cmd_socket, host.zmq_observation_socket):
        socket.setsockopt(zmq.LINGER, 0)
    def port(socket):
        return int(socket.getsockopt(zmq.LAST_ENDPOINT).decode().rsplit(":", 1)[1])
    client = SourcceyClient(SourcceyClientConfig(
        remote_ip="127.0.0.1", calibration_dir=tmp_path, cameras={},
        port_zmq_cmd=port(host.zmq_cmd_socket),
        port_zmq_observations=port(host.zmq_observation_socket), connect_timeout_s=2,
    ))
    payload = SourcceyProtobuf().observation_to_protobuf({
        "z.pos": 12.0, "front_left": np.ones((24, 32, 3), dtype=np.uint8),
    }).SerializeToString()
    stop = Event()
    def publish():
        while not stop.is_set():
            try:
                host.zmq_observation_socket.send(payload, zmq.NOBLOCK)
            except zmq.Again:
                pass
            stop.wait(0.01)
    publisher = Thread(target=publish)
    publisher.start()
    try:
        client.connect()
        assert client.is_connected
        state = sourccey_pb2.SourcceyRobotState.FromString(client._pending_observation_bytes)
        observation = SourcceyProtobuf().protobuf_to_observation(state)
        assert observation["z.pos"] == 12.0
        assert observation["front_left"].shape == (24, 32, 3)
    finally:
        stop.set()
        publisher.join(timeout=3)
        if client.is_connected:
            client.disconnect()
        host.disconnect()
