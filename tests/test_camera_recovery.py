from threading import Event, Thread
from unittest.mock import Mock

import lerobot_robot_sourccey.cameras.opencv as module
import numpy as np
import pytest
from lerobot_robot_sourccey.cameras import (
    SourcceyOpenCVCamera,
    SourcceyOpenCVCameraConfig,
)

from lerobot.utils.errors import DeviceNotConnectedError


def camera(**kwargs):
    result = SourcceyOpenCVCamera(SourcceyOpenCVCameraConfig(index_or_path=0, **kwargs))
    result.stop_event = Event()
    return result


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_consecutive_read_failures", 0),
        ("max_consecutive_read_failures", True),
        ("max_consecutive_read_failures", 1.5),
        ("fast_reconnect_interval_s", -1),
        ("fast_reconnect_window_s", float("nan")),
        ("reconnect_interval_s", float("inf")),
    ],
)
def test_recovery_config_validation(field, value):
    with pytest.raises(ValueError):
        camera(**{field: value})


def test_reconnect_releases_old_capture_and_invalidates_old_frame(monkeypatch):
    device = camera()
    old, new = Mock(), Mock()
    device.videocapture = old
    device.latest_frame = np.ones((2, 2, 3))
    device.latest_timestamp = 12.0
    device.new_frame_event.set()
    monkeypatch.setattr(module.cv2, "VideoCapture", Mock(return_value=new))
    device._configure_capture_settings = Mock()
    assert device._recover(ConnectionError("unplugged"))
    old.release.assert_called_once()
    device._configure_capture_settings.assert_called_once()
    assert device.videocapture is new
    assert device.latest_frame is None
    assert device.latest_timestamp is None
    assert not device.new_frame_event.is_set()
    device.disconnect()
    new.release.assert_called_once()


def test_failed_configuration_is_released_before_retry(monkeypatch):
    device = camera(fast_reconnect_interval_s=0)
    rejected, good = Mock(), Mock()
    monkeypatch.setattr(module.cv2, "VideoCapture", Mock(side_effect=[rejected, good]))
    device._configure_capture_settings = Mock(side_effect=[ValueError("bad resolution"), None])
    assert device._recover(ConnectionError())
    rejected.release.assert_called_once()
    assert device.videocapture is good
    device.disconnect()


def test_retry_delay_switches_from_fast_to_steady(monkeypatch):
    device = camera(fast_reconnect_interval_s=0.05, fast_reconnect_window_s=2, reconnect_interval_s=0.5)
    stop = Mock()
    stop.is_set.side_effect = [False, False, False, True]
    device.stop_event = stop
    monkeypatch.setattr(module.time, "monotonic", Mock(side_effect=[0, 0.1, 3]))
    captures = [Mock(isOpened=Mock(return_value=False)), Mock(isOpened=Mock(return_value=False))]
    monkeypatch.setattr(module.cv2, "VideoCapture", Mock(side_effect=captures))
    assert not device._recover(ConnectionError())
    assert [call.args[0] for call in stop.wait.call_args_list] == [0.05, 0.5]
    for capture in captures:
        capture.release.assert_called_once()


def test_disconnect_interrupts_long_retry_wait(monkeypatch):
    device = camera(fast_reconnect_window_s=0, reconnect_interval_s=60)
    attempted = Event()
    opened = Mock(isOpened=Mock(return_value=False))

    def open_capture(*args):
        attempted.set()
        return opened

    monkeypatch.setattr(module.cv2, "VideoCapture", open_capture)
    worker = Thread(target=device._recover, args=(ConnectionError(),))
    device.thread = worker
    worker.start()
    assert attempted.wait(1)
    device.disconnect()
    assert not worker.is_alive()
    assert device.videocapture is None


def test_stop_during_successful_reopen_releases_new_capture(monkeypatch):
    device = camera()
    opened = Mock()
    monkeypatch.setattr(module.cv2, "VideoCapture", Mock(return_value=opened))
    device._configure_capture_settings = lambda: device.stop_event.set()
    assert not device._recover(ConnectionError())
    opened.release.assert_called_once()
    assert device.videocapture is None


@pytest.mark.parametrize("error", [ConnectionError("read failed"), DeviceNotConnectedError("unplugged")])
def test_read_loop_recovers_then_publishes_new_frame(error):
    device = camera()
    frame = np.ones((2, 2, 3), dtype=np.uint8)
    calls = 0

    def read():
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise error
        device.stop_event.set()
        return frame

    device._read_from_hardware = read
    device._postprocess_image = lambda image: image
    device._recover = Mock(return_value=True)
    device._read_loop()
    assert device._recover.called
    np.testing.assert_array_equal(device.latest_frame, frame)
    assert device.new_frame_event.is_set()


def test_disabled_recovery_raises_without_reopening(monkeypatch):
    device = camera(auto_reconnect=False, max_consecutive_read_failures=1)
    opener = Mock()
    monkeypatch.setattr(module.cv2, "VideoCapture", opener)
    device._read_from_hardware = Mock(side_effect=ConnectionError("failed"))
    with pytest.raises(RuntimeError, match="consecutive"):
        device._read_loop()
    opener.assert_not_called()
