from __future__ import annotations

import contextlib
import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lerobot_robot_sourccey.robots.sourccey_z_actuator.sourccey_z_calibrator import SourcceyZCalibrator
from lerobot.utils.constants import HF_LEROBOT_CALIBRATION, ROBOTS
from lerobot.utils.robot_utils import precise_sleep
from lerobot_robot_sourccey.utils.spi_lock import spi_device_lock

try:
    from gpiozero import MCP3008  # type: ignore
except Exception:  # pragma: no cover
    MCP3008 = None  # type: ignore


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZActuatorReading:
    raw: int        # 0..1023 (native MCP3008)
    voltage: float  # volts at the MCP3008 pin


@dataclass(frozen=True)
class ZActuatorCalibration:
    raw_min: int
    raw_max: int
    invert: bool

class ZMotorDriver(Protocol):
    """Small protocol so we can inject Sourccey’s DC controller without importing it here."""
    def set_velocity(self, motor: str | int, velocity: float, normalize: bool = True, instant: bool = True) -> None: ...
    def set_pwm(self, motor: str | int, duty_cycle: float) -> None: ...


class ZSensor:
    """
    Potentiometer sensor reader via MCP3008.

    - Raw MCP3008 is 10-bit (0..1023).
    - We keep everything in native units for calibration and conversion.
    - Calibration maps raw -> position in [-100, 100].
    """

    def __init__(
        self,
        *,
        adc_channel: int = 1,
        vref: float = 3.30,
        average_samples: int = 50,
        invert: bool = True,  # invert published position convention (e.g. make "up" positive)
    ) -> None:
        self.adc_channel = int(adc_channel)
        self.vref = float(vref)
        self.average_samples = int(average_samples)

        # Calibration bounds in native MCP3008 units.
        self.raw_min = 0
        self.raw_max = 1023
        self.calibration_min = self.raw_min
        self.calibration_max = self.raw_max
        self.invert = bool(invert)

        self._adc: MCP3008 | None = None

        # A disconnected potentiometer/SPI hiccup commonly reads the opposite ADC
        # rail for one cycle.  Without filtering, +100 can therefore appear as
        # -100 and be fed straight back into both the position controller and a
        # recorded action.  Confirm implausibly large jumps before publishing them.
        self.max_position_jump: float = 40.0
        self.jump_confirmation_reads: int = 2
        self._last_position: float | None = None
        self._jump_candidate: float | None = None
        self._jump_candidate_reads: int = 0
        self._position_lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self._adc is not None

    def connect(self) -> None:
        if MCP3008 is None:
            raise RuntimeError("gpiozero is not installed; MCP3008 is unavailable on this machine.")
        if self._adc is None:
            candidate = None
            try:
                candidate = MCP3008(channel=self.adc_channel)
                _ = candidate.raw_value  # probe once to confirm the ADC responds
            except RuntimeError:
                raise  # Re-raise our floating signal error
            except Exception as exc:
                if candidate is not None:
                    with contextlib.suppress(Exception):
                        candidate.close()  # type: ignore[attr-defined]
                print(f"Failed to initialize MCP3008 on channel {self.adc_channel}. {exc}")

            self._adc = candidate
            if self._adc is not None:
                self.reset_position_filter()

    def disconnect(self) -> None:
        if self._adc is not None:
            close = getattr(self._adc, "close", None)
            if callable(close):
                close()
            self._adc = None
            self.reset_position_filter()

    def set_calibration(self, *, raw_min: int, raw_max: int, invert: bool | None = None) -> None:
        self.calibration_min = int(raw_min)
        self.calibration_max = int(raw_max)
        if invert is not None:
            self.invert = bool(invert)
        self.reset_position_filter()

    def reset_position_filter(self) -> None:
        """Forget read history after connecting or changing calibration."""
        with self._position_lock:
            self._last_position = None
            self._jump_candidate = None
            self._jump_candidate_reads = 0

    @staticmethod
    def _clamp(x: float, lo: float, hi: float) -> float:
        return lo if x < lo else hi if x > hi else x


    ############################################################
    # Read Functions
    ############################################################
    def read_raw(self) -> ZActuatorReading:
        """Read averaged raw (0..1023) and voltage."""
        if self._adc is None:
            self.connect()
        assert self._adc is not None

        # Guard with a cross-process lock because battery.py may run concurrently
        # and access the same MCP3008 over SPI.
        with spi_device_lock():
            total = 0.0
            for _ in range(self.average_samples):
                total += float(self._adc.raw_value)
        raw = int(round(total / self.average_samples))
        voltage = (raw / 1023.0) * self.vref
        return ZActuatorReading(raw=raw, voltage=voltage)

    def read_position_m100_100(self) -> float:
        measured = self.raw_to_pos_m100_100(self.read_raw().raw)
        with self._position_lock:
            if self._last_position is None:
                self._last_position = measured
                return measured

            if abs(measured - self._last_position) <= self.max_position_jump:
                self._last_position = measured
                self._jump_candidate = None
                self._jump_candidate_reads = 0
                return measured

            if (
                self._jump_candidate is not None
                and abs(measured - self._jump_candidate) <= self.max_position_jump
            ):
                self._jump_candidate_reads += 1
            else:
                self._jump_candidate = measured
                self._jump_candidate_reads = 1

            if self._jump_candidate_reads >= self.jump_confirmation_reads:
                self._last_position = measured
                self._jump_candidate = None
                self._jump_candidate_reads = 0

            return self._last_position

    ############################################################
    # Conversion Functions
    ############################################################

    def raw_to_pos_m100_100(self, raw: int) -> float:
        """Convert native raw (0..1023) into position [-100, 100] using current calibration."""
        rmin, rmax = float(self.calibration_min), float(self.calibration_max)
        if rmax == rmin:
            return 0.0

        t = (float(raw) - rmin) / (rmax - rmin)  # 0..1 ideally
        t = self._clamp(t, 0.0, 1.0)
        pos = -100.0 + 200.0 * t  # -100..100

        # Sensor invert: ensures your published position follows your chosen convention (e.g. "up is +")
        return -pos if self.invert else pos

    def position_m100_100_to_raw(self, position: float) -> int:
        """Map [-100,100] -> [calibration_min, calibration_max] (inverse of raw_to_pos_m100_100)."""
        p = self._clamp(float(position), -100.0, 100.0)
        if self.invert:
            p = -p
        t = (p + 100.0) / 200.0
        rmin, rmax = float(self.calibration_min), float(self.calibration_max)
        return int(round(rmin + t * (rmax - rmin)))


class SourcceyZActuator:
    """
    Higher-level Z module:
    - reads position through a ZSensor
    - writes motor commands through an injected driver (e.g. Sourccey’s PWM DC controller)

    This keeps the ADC concerns (sensor) separate from actuation concerns (motor driver).
    """

    def __init__(
        self,
        *,
        sensor: ZSensor,
        driver: ZMotorDriver | None = None,
        motor: str | int = "linear_actuator",
        motor_invert: bool = True,
        proportional_gain: float = 0.035,
        minimum_up_command: float = 0.82,
        minimum_down_command: float = 0.82,
        maximum_command: float = 1.0,
        position_deadband: float = 0.75,
        control_hz: float = 50.0,
    ) -> None:

        self.name = "sourccey_z_actuator"

        self.sensor = sensor
        self.driver = driver
        self.motor = motor
        self.use_z_actuator = False

        self.motor_invert = bool(motor_invert)
        self.invert = sensor.invert

        # A deliberately small P-only controller. Minimum drive compensates for
        # actuator stiction; separate up/down values allow gravity compensation.
        self.proportional_gain = max(0.0, float(proportional_gain))
        self.minimum_up_command = self._clamp_command_magnitude(minimum_up_command)
        self.minimum_down_command = self._clamp_command_magnitude(minimum_down_command)
        self.maximum_command = self._clamp_command_magnitude(maximum_command)
        self.position_deadband = max(0.0, float(position_deadband))
        self.control_hz = max(1.0, float(control_hz))
        if self.minimum_up_command > self.maximum_command:
            raise ValueError("minimum_up_command cannot exceed maximum_command")
        if self.minimum_down_command > self.maximum_command:
            raise ValueError("minimum_down_command cannot exceed maximum_command")

        self._target_lock = threading.Lock()
        self._target_pos_m100_100 = 0.0
        self._target_initialized = False
        self._last_error_sign = 0
        self._settled_target: float | None = None
        self._debug_mode = False
        self._last_debug_t = 0.0

        # Calibration
        self.calibration_dir = (
            HF_LEROBOT_CALIBRATION / ROBOTS / self.name
        )
        self.calibration_dir.mkdir(parents=True, exist_ok=True)
        self.calibration_fpath = self.calibration_dir / f"{self.name}.json"
        self.calibration: dict[str, ZActuatorCalibration] = {}
        if self.calibration_fpath.is_file():
            self._load_calibration()

        self.calibrator = SourcceyZCalibrator(self)

        self._ctl_stop_event = threading.Event()
        self._ctl_thread: threading.Thread | None = None

    @staticmethod
    def _clamp_command_magnitude(command: float) -> float:
        return max(0.0, min(1.0, float(command)))

    @property
    def is_connected(self) -> bool:
        return self.sensor.is_connected

    def connect(self) -> None:
        self.sensor.connect()
        self.use_z_actuator = bool(self.sensor.is_connected)
        if self.use_z_actuator:
            # Starting the controller must never move Z before the first command.
            self.write_position(self.read_position())

    def disconnect(self) -> None:
        # Ensure no background thread is still calling update() while we disconnect the ADC.
        self.stop_position_controller()
        self.sensor.disconnect()

    def compute_command(self, position: float, target: float) -> float:
        """Return a normalized logical command from calibrated position error."""
        position = float(position)
        target = max(-100.0, min(100.0, float(target)))
        if not math.isfinite(position) or not math.isfinite(target):
            return 0.0

        error = target - position
        abs_error = abs(error)
        if abs_error <= self.position_deadband:
            return 0.0

        minimum_command = self.minimum_up_command if error > 0.0 else self.minimum_down_command
        proportional_error = abs_error - self.position_deadband
        magnitude = minimum_command + self.proportional_gain * proportional_error
        magnitude = min(self.maximum_command, magnitude)
        return magnitude if error > 0.0 else -magnitude

    def update(self, dt_s: float = 0.0, *, instant: bool = True) -> float:
        """Run one deterministic position-control update."""
        del dt_s  # P-only control is intentionally independent of loop jitter.
        if self.driver is None:
            raise RuntimeError("No driver provided. Pass `driver=...` (e.g. Sourccey.dc_motors_controller).")

        position = float(self.read_position())
        with self._target_lock:
            target = self._target_pos_m100_100
            settled = self._settled_target == target
            error = target - position
            error_sign = 1 if error > 0.0 else -1 if error < 0.0 else 0
            crossed_target = (
                self._last_error_sign != 0
                and error_sign != 0
                and error_sign != self._last_error_sign
            )
            if crossed_target:
                self._settled_target = target
                settled = True
            if not settled and error_sign != 0:
                self._last_error_sign = error_sign

        logical_command = 0.0 if settled else self.compute_command(position, target)
        motor_command = -logical_command if self.motor_invert else logical_command
        self.driver.set_velocity(self.motor, motor_command, normalize=True, instant=instant)

        now = time.monotonic()
        if self._debug_mode and now - self._last_debug_t >= 1.0:
            self._last_debug_t = now
            print(
                {
                    "z_pos": round(position, 2),
                    "z_target": round(target, 2),
                    "z_error": round(target - position, 2),
                    "z_command": round(logical_command, 3),
                }
            )
        return position


    ############################################################
    # Control Functions
    ############################################################
    def _control_loop(self) -> None:
        period = 1.0 / self.control_hz
        next_tick = time.monotonic()
        while not self._ctl_stop_event.is_set():
            try:
                self.update(instant=True)
            except Exception as exc:
                logger.warning("Z position-control update failed; stopping motor: %s", exc)
                with contextlib.suppress(Exception):
                    self.stop()
                if self._ctl_stop_event.wait(0.1):
                    break

            next_tick += period
            remaining = next_tick - time.monotonic()
            if remaining > 0.0:
                precise_sleep(remaining)
            else:
                # Do not burst multiple updates after an ADC/SPI scheduling delay.
                next_tick = time.monotonic()

        with contextlib.suppress(Exception):
            self.stop()

    def _ensure_controller_running(self) -> None:
        if self._ctl_thread is not None and self._ctl_thread.is_alive():
            return

        self._ctl_stop_event.clear()
        self._ctl_thread = threading.Thread(
            target=self._control_loop,
            name="SourcceyZActuatorControl",
            daemon=True,
        )
        self._ctl_thread.start()

    def stop_position_controller(self, *, join_timeout_s: float = 1.0) -> None:
        """Stop the background position controller (if running) and stop motor output."""
        self._ctl_stop_event.set()
        t = self._ctl_thread
        if t is not None and t.is_alive():
            t.join(timeout=float(join_timeout_s))
        self._ctl_thread = None
        self.stop()

    def stop(self) -> None:
        """Stop motor output."""
        if self.driver is not None:
            self.driver.set_velocity(self.motor, 0.0, normalize=True, instant=True)

    ############################################################
    # Calibration Functions
    ############################################################
    def _load_calibration(self, fpath: Path | None = None) -> bool:
        """
        Load Z sensor calibration from `<calibration_dir>/<filename>`.

        Expected JSON:
          "z_actuator": {
            "raw_min": 123,
            "raw_max": 987,
            "invert": true   # optional
          }

        Returns True if loaded, False if file doesn't exist.
        """
        fpath = self.calibration_fpath if fpath is None else fpath
        if not fpath.is_file():
            return False

        try:
            with open(fpath) as f:
                data = json.load(f)

            raw_min = int(data["z_actuator"]["raw_min"])
            raw_max = int(data["z_actuator"]["raw_max"])
            invert = bool(data["z_actuator"]["invert"])
        except Exception as exc:
            logger.warning(
                "Failed to load Z actuator calibration from %s: %s. "
                "Starting with defaults and allowing recalibration.",
                fpath,
                exc,
            )
            return False

        self.sensor.set_calibration(raw_min=raw_min, raw_max=raw_max, invert=invert)

        # Keep the published position convention consistent with sensor inversion.
        self.invert = bool(self.sensor.invert)
        return True

    def _save_calibration(self, fpath: Path | None = None) -> None:
        """
        Save Z sensor calibration to `<calibration_dir>/<filename>`.
        """
        fpath = self.calibration_fpath if fpath is None else fpath
        with open(fpath, "w") as f:
            json.dump({
                "z_actuator": {
                    "raw_min": self.sensor.calibration_min,
                    "raw_max": self.sensor.calibration_max,
                    "invert": self.sensor.invert
                }
            }, f, indent=4)

    ############################################################
    # Read / Write Functions
    ############################################################

    # --- Reads (delegated to sensor) ---
    def read_position(self) -> float:
        return self.sensor.read_position_m100_100()

    # --- Write Functions ---
    def write_position(self, target_pos_m100_100: float) -> None:
        target = float(target_pos_m100_100)
        if not math.isfinite(target):
            raise ValueError("Z position target must be finite")
        with self._target_lock:
            target = max(-100.0, min(100.0, target))
            if target != self._target_pos_m100_100:
                self._settled_target = None
                self._last_error_sign = 0
            self._target_pos_m100_100 = target
            self._target_initialized = True

    ############################################################
    # Move Position Functions
    ############################################################
    def move_to_position(
        self,
        target_pos_m100_100: float,
        *,
        hz: float | None = None,
        instant: bool = True,
    ) -> None:
        """Set a position target and ensure the background controller is running."""
        if self.driver is None:
            raise RuntimeError("No driver provided. Pass `driver=...` to move the actuator.")

        if hz is not None:
            self.control_hz = max(1.0, float(hz))
        self.write_position(float(target_pos_m100_100))
        del instant  # Retained for compatibility with existing callers.
        self._ensure_controller_running()

    def move_to_position_blocking(
        self,
        target_pos_m100_100: float,
        *,
        timeout_s: float = 10.0,
        hz: float | None = None,
        instant: bool = True,
    ) -> float:
        """
        Blocking move: set a target position and drive until within deadband (or timeout).
        Returns the final measured position.
        """
        if self.driver is None:
            raise RuntimeError("No driver provided. Pass `driver=...` to move the actuator.")

        # Avoid concurrent control from background thread.
        self.stop_position_controller()

        self.write_position(float(target_pos_m100_100))

        update_hz = self.control_hz if hz is None else max(1.0, float(hz))
        period = 1.0 / update_hz
        t_end = time.monotonic() + float(timeout_s)
        last_t = time.monotonic()

        while True:
            now = time.monotonic()
            if now >= t_end:
                self.stop()
                raise TimeoutError(f"Timed out moving Z to {target_pos_m100_100}")

            dt = now - last_t
            last_t = now
            pos = self.update(dt, instant=instant)

            if abs(pos - float(target_pos_m100_100)) <= self.position_deadband:
                self.stop()
                return pos

            time.sleep(period)

