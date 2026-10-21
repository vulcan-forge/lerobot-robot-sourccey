"""Desktop key-state bridge and local keyboard input owned by Sourccey."""

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from lerobot.teleoperators import Teleoperator, TeleoperatorConfig
from lerobot.utils.errors import DeviceAlreadyConnectedError


@TeleoperatorConfig.register_subclass("sourccey_keyboard")
@dataclass
class SourcceyKeyboardConfig(TeleoperatorConfig):
    """Select local keyboard capture or a desktop JSON key-state file."""

    input_state_path: str | None = None
    # Enable a timeout when the desktop writer refreshes held-key snapshots.
    input_state_timeout_s: float | None = None

    def __post_init__(self) -> None:
        if self.input_state_timeout_s is not None and (
            not math.isfinite(self.input_state_timeout_s) or self.input_state_timeout_s <= 0
        ):
            raise ValueError("input_state_timeout_s must be positive")


class SourcceyKeyboard(Teleoperator):
    """Read held keys and preserve key-down events between control ticks."""

    config_class = SourcceyKeyboardConfig
    name = "sourccey_keyboard"

    def __init__(self, config: SourcceyKeyboardConfig) -> None:
        super().__init__(config)
        self.config = config
        self.listener: Any = None
        self._connected = False
        self._pressed: set[str] = set()
        self._edges: list[str] = []
        self._queue: Queue[tuple[str, bool]] = Queue()

    @property
    def action_features(self) -> dict[str, type]:
        return {}

    @property
    def feedback_features(self) -> dict[str, type]:
        return {}

    @property
    def is_connected(self) -> bool:
        return self._connected and (self.config.input_state_path is not None or (self.listener is not None and self.listener.is_alive()))

    @property
    def is_calibrated(self) -> bool:
        return True

    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise DeviceAlreadyConnectedError("Sourccey keyboard is already connected")
        self._pressed.clear()
        self._edges.clear()
        if self.config.input_state_path is None:
            # Import only for local input: the desktop bridge works headlessly.
            from pynput import keyboard

            self.listener = keyboard.Listener(
                on_press=lambda key: self._enqueue(key, True),
                on_release=lambda key: self._enqueue(key, False),
            )
            self.listener.start()
            self.listener.wait()
        self._connected = True

    def _enqueue(self, key: Any, pressed: bool) -> None:
        name = getattr(key, "char", None) or getattr(key, "name", "")
        name = {"right": "arrowright", "left": "arrowleft", "esc": "escape"}.get(name, name)
        if name:
            self._queue.put((name.lower(), pressed))

    def _drain(self) -> None:
        if not self.is_connected:
            self._pressed.clear()
            self._edges.clear()
            return
        if self.config.input_state_path is not None:
            path = Path(self.config.input_state_path)
            try:
                if (
                    self.config.input_state_timeout_s is not None
                    and time.time() - path.stat().st_mtime > self.config.input_state_timeout_s
                ):
                    raise ValueError("Stale desktop key state")
                values = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(values, list) or not all(isinstance(key, str) for key in values):
                    raise ValueError("keys must be a list of strings")
                pressed = {key.lower() for key in values}
            except (OSError, ValueError, TypeError):
                pressed = set()
            self._edges.extend(sorted(pressed - self._pressed))
            self._pressed = pressed
        else:
            while True:
                try:
                    key, pressed = self._queue.get_nowait()
                except Empty:
                    break
                if pressed:
                    if key not in self._pressed:
                        self._edges.append(key)
                    self._pressed.add(key)
                else:
                    self._pressed.discard(key)

    def get_action(self) -> dict[str, None]:
        self._drain()
        return dict.fromkeys(self._pressed)

    def pop_key_down_edges(self) -> list[str]:
        self._drain()
        edges, self._edges = self._edges, []
        return edges

    def disconnect(self) -> None:
        self._connected = False
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        self._pressed.clear()
        self._edges.clear()
        while not self._queue.empty():
            self._queue.get_nowait()

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        pass
