from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import zmq
from lerobot_robot_sourccey.diagnostics import camera_remote, lidar_imu, motors


@pytest.mark.parametrize("fault", ["timeout", "decode", "endpoint"])
def test_failed_observation_connection_closes_socket_and_context(monkeypatch, fault):
    socket = Mock(recv=Mock(return_value=b"invalid packet"))
    context = Mock(socket=Mock(return_value=socket))
    poller = Mock(poll=Mock(return_value=[] if fault == "timeout" else [(socket, zmq.POLLIN)]))
    monkeypatch.setattr(camera_remote.zmq, "Context", Mock(return_value=context))
    monkeypatch.setattr(camera_remote.zmq, "Poller", Mock(return_value=poller))
    receiver = camera_remote.ObservationSubscriber("127.0.0.1", 5556)
    if fault == "decode":
        receiver._ingest = Mock(side_effect=ValueError("invalid packet"))
    if fault == "endpoint":
        socket.connect.side_effect = zmq.ZMQError("bad endpoint")
    with pytest.raises((TimeoutError, ValueError, zmq.ZMQError)):
        receiver.connect()
    socket.close.assert_called_once_with(0)
    context.term.assert_called_once()
    assert receiver._socket is None and receiver._context is None


@pytest.mark.parametrize("key", ["left_shoulder_pan.pos", "z.pos"])
def test_remote_motor_check_rejects_unavailable_telemetry(monkeypatch, key):
    state = {f"{side}_{joint}.pos": 1.0 for side in ("left", "right") for joint in motors.JOINT_ORDER}
    state.update({"z.pos": 0.0, "x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})
    state[key] = float("nan")
    subscriber = Mock(state=Mock(return_value=state))
    monkeypatch.setattr(motors, "ObservationSubscriber", Mock(return_value=subscriber))
    monkeypatch.setattr(motors.time, "sleep", lambda seconds: None)
    args = SimpleNamespace(remote_ip="127.0.0.1", port=5556, connect_timeout=1, remote_seconds=0)
    assert not motors.check_remote(args)
    subscriber.close.assert_called_once()


def test_imu_read_exception_still_disconnects(monkeypatch):
    backend = Mock(read=Mock(side_effect=OSError("I2C failure")))
    monkeypatch.setattr(lidar_imu, "AdafruitLSM6DSOXLIS3MDLIMU", Mock(return_value=backend))
    monkeypatch.setattr(lidar_imu, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 0.1])))
    args = SimpleNamespace(
        imu_bus=1, imu_accel_address=0x6A, imu_mag_address=0x1C, imu_seconds=1, spin_test=False
    )
    assert not lidar_imu.check_imu(args)
    backend.disconnect.assert_called_once()


def test_spin_test_rejects_invalid_backend_samples(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda message: "")
    monkeypatch.setattr(lidar_imu, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 0.1])))
    imu = Mock(read=Mock(return_value=SimpleNamespace(valid=False, error="I2C failure")))
    assert not lidar_imu._run_spin_test(imu, SimpleNamespace(spin_seconds=1))
