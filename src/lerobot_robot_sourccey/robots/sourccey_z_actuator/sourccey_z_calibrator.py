from dataclasses import dataclass
import logging
import time


logger = logging.getLogger(__name__)


class CalibrationPhaseError(RuntimeError):
    """Raised when a calibration phase cannot complete safely or verifiably."""


@dataclass(frozen=True)
class ZCalibrationResult:
    raw_bottom: int
    raw_top: int
    raw_min: int
    raw_max: int
    invert: bool


class SourcceyZCalibrator:
    """
    Autocalibration by stall detection:

    - Drive DOWN at constant command until sensor raw ADC counts stop changing for `stable_s`
    - Drive back UP at constant command until sensor raw ADC counts stop changing for `stable_s`

    Then write calibration to the ZSensor.

    Notes:
    - This assumes your motor driver / mechanics can safely hit end stops (current limiting!).
    - 'Stable' is defined as abs(raw - last_raw) <= stable_eps_raw continuously for stable_s.
    """

    TOP_VERIFY_TOLERANCE_RAW = 12
    SEEK_BOTTOM_MIN_DRIVE_S = 1.0
    # Endpoint seeking must also work when calibration starts with the actuator
    # already resting on an end stop. Stability plus the minimum drive time
    # confirms the endpoint without requiring prior sensor travel.
    SEEK_BOTTOM_MIN_TRAVEL_RAW = 0
    RETURN_TOP_MIN_DRIVE_S = 1.0
    RETURN_TOP_MIN_TRAVEL_RAW = 0

    def __init__(
        self,
        actuator,  # SourcceyZActuator
        *,
        # Require continuous stability long enough to distinguish an endpoint
        # from a brief mid-stroke hesitation without adding excessive dwell.
        stable_s: float = 3.0,
        sample_hz: float = 30.0,
        stable_eps_pos: float = 1.0,
        stable_eps_raw: int = 2,
        # Allow a full stroke plus the endpoint stability confirmation above.
        max_phase_s: float = 60.0,
        down_cmd: float = -1.0,
        up_cmd: float = 1.0,
    ) -> None:
        self.actuator = actuator
        self.stable_s = float(stable_s)
        self.sample_hz = float(sample_hz)
        # Backward-compat field kept for callers passing this argument.
        # Stall detection now uses native raw units via `stable_eps_raw`.
        self.stable_eps_pos = float(stable_eps_pos)
        self.stable_eps_raw = int(stable_eps_raw)
        self.max_phase_s = float(max_phase_s)
        self.down_cmd = float(down_cmd)
        self.up_cmd = float(up_cmd)
        self._last_move_travel_raw = 0

    def _log_phase(self, phase: str, *, event: str, started_at: float, **fields: object) -> None:
        elapsed_s = time.monotonic() - started_at
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info(
            "z_phase=%s event=%s elapsed_s=%.2f%s%s",
            phase,
            event,
            elapsed_s,
            " " if suffix else "",
            suffix,
        )

    def _drive(self, cmd: float) -> None:
        cmd = -cmd if self.actuator.motor_invert else cmd
        if self.actuator.driver is None:
            raise RuntimeError("SourcceyZActuator has no driver; cannot drive motor.")
        # Important: cmd sign here is MOTOR sign. If this moves opposite of expected, swap down_cmd/up_cmd.
        self.actuator.driver.set_velocity(self.actuator.motor, float(cmd), normalize=True, instant=True)

    def _read_pos(self) -> float:
        return float(self.actuator.sensor.read_position_m100_100())

    def _read_raw(self) -> int:
        """Read native MCP3008 units (0..1023)."""
        return int(self.actuator.sensor.read_raw().raw)

    def _wait_until_stable(
        self,
        cmd: float,
        *,
        phase: str,
        min_elapsed_s: float = 0.0,
        min_travel_raw: int = 0,
    ) -> int:
        period = 1.0 / max(1.0, self.sample_hz)
        started_at = time.monotonic()
        t_deadline = started_at + self.max_phase_s

        # Detect stall in raw ADC counts so calibration sensitivity is independent
        # of any prior saved mapping.
        start_raw = None
        last_raw = None
        stable_start = None
        stable_anchor_raw = None
        max_travel_raw = 0
        min_elapsed_s = float(min_elapsed_s)
        min_travel_raw = int(min_travel_raw)

        while True:
            now = time.monotonic()
            if now >= t_deadline:
                self._last_move_travel_raw = int(max_travel_raw)
                raise TimeoutError(
                    "Z calibrator timed out waiting for stability "
                    f"(phase={phase}, start_raw={start_raw}, last_raw={last_raw}, "
                    f"travel_raw={max_travel_raw}, min_travel_raw={min_travel_raw}, "
                    f"stable_eps_raw={self.stable_eps_raw}, stable_s={self.stable_s})."
                )

            # KEEP MOTOR ALIVE (important for watchdog-style drivers)
            self._drive(cmd)

            raw = self._read_raw()

            if start_raw is None:
                start_raw = raw
            else:
                max_travel_raw = max(max_travel_raw, abs(int(raw) - int(start_raw)))

            if last_raw is None:
                last_raw = raw
                stable_start = None
            else:
                elapsed_s = now - started_at
                if elapsed_s < min_elapsed_s or max_travel_raw < min_travel_raw:
                    stable_start = None
                    stable_anchor_raw = None
                elif stable_start is None or stable_anchor_raw is None:
                    stable_start = now
                    stable_anchor_raw = raw
                elif abs(raw - stable_anchor_raw) > self.stable_eps_raw:
                    # Compare against the beginning of the stability window,
                    # not merely the previous sample. Otherwise slow movement
                    # (for example one raw count per sample) looks stationary.
                    stable_start = now
                    stable_anchor_raw = raw
                elif (now - stable_start) >= self.stable_s:
                    self._last_move_travel_raw = int(max_travel_raw)
                    return raw

                last_raw = raw

            time.sleep(period)

    def _move_to_endpoint(
        self,
        cmd: float,
        *,
        phase: str,
        min_elapsed_s: float = 0.0,
        min_travel_raw: int = 0,
    ) -> int:
        """Drive to a hard endpoint and stop once the raw reading is stable."""
        started_at = time.monotonic()
        self._log_phase(
            phase,
            event="start",
            started_at=started_at,
            cmd=round(float(cmd), 3),
            min_elapsed_s=round(float(min_elapsed_s), 3),
            min_travel_raw=int(min_travel_raw),
        )
        self._drive(cmd)
        raw = self._wait_until_stable(
            cmd,
            phase=phase,
            min_elapsed_s=min_elapsed_s,
            min_travel_raw=min_travel_raw,
        )
        self.actuator.stop()
        time.sleep(0.25)
        self._log_phase(
            phase,
            event="stop",
            started_at=started_at,
            raw=int(raw),
            travel_raw=int(self._last_move_travel_raw),
        )
        return int(raw)

    def _verify_top(self, *, expected_raw_top: int) -> int:
        started_at = time.monotonic()
        observed_raw = self._read_raw()
        delta = abs(int(observed_raw) - int(expected_raw_top))
        self._log_phase(
            "verify_top",
            event="check",
            started_at=started_at,
            observed_raw=int(observed_raw),
            expected_raw=int(expected_raw_top),
            delta_raw=int(delta),
            tolerance_raw=self.TOP_VERIFY_TOLERANCE_RAW,
        )
        if delta > self.TOP_VERIFY_TOLERANCE_RAW:
            raise CalibrationPhaseError(
                "z:return_top verification failed "
                f"(observed_raw={observed_raw}, expected_raw={expected_raw_top}, tolerance_raw={self.TOP_VERIFY_TOLERANCE_RAW})"
            )
        self._log_phase("verify_top", event="pass", started_at=started_at, observed_raw=int(observed_raw))
        return int(observed_raw)

    def _return_to_top_and_verify(self) -> int:
        try:
            raw_top = self._move_to_endpoint(
                self.up_cmd,
                phase="return_top",
                min_elapsed_s=self.RETURN_TOP_MIN_DRIVE_S,
                min_travel_raw=self.RETURN_TOP_MIN_TRAVEL_RAW,
            )
        except Exception as exc:
            raise CalibrationPhaseError("z:return_top drive failed") from exc

        return self._verify_top(expected_raw_top=raw_top)

    def _wait_for_seconds(self, cmd: float, seconds: float) -> int:
        """
        Drive at `cmd` for a fixed time (no end-stop detection).
        Returns the last raw value (0..1023) sampled during the window.

        Useful for "soft" calibration where you *don't* want to hit the mechanical edge.
        """
        period = 1.0 / max(1.0, self.sample_hz)
        t_end = time.monotonic() + float(seconds)

        last_raw = self._read_raw()
        while time.monotonic() < t_end:
            # Keep refreshing the motor command while we wait
            self._drive(cmd)
            last_raw = self._read_raw()
            time.sleep(period)

        return int(last_raw)

    def default_calibrate(self) -> ZCalibrationResult:
        """
        Soft calibration path.

        This path intentionally does not move the Z actuator. It reuses the
        currently loaded sensor calibration values and persists them, which is
        the expected behavior for non-`full_reset` robot auto-calibration.
        """
        try:
            if not self.actuator.is_connected:
                logger.warning("Z default calibration aborted: actuator is not connected")
                return None
        except Exception as e:
            logger.exception("Z default calibration failed while checking actuator connection: %s", e)
            print(f"Error: actuator is not connected: {e}")
            return None

        try:
            self.actuator.stop_position_controller()
        except Exception:
            pass

        raw_min = int(self.actuator.sensor.calibration_min)
        raw_max = int(self.actuator.sensor.calibration_max)
        invert = bool(self.actuator.sensor.invert)

        self.actuator.sensor.set_calibration(raw_min=raw_min, raw_max=raw_max, invert=invert)
        self.actuator.invert = bool(self.actuator.sensor.invert)
        self.actuator._save_calibration()
        logger.info(
            "Z default calibration completed without movement: raw_min=%s raw_max=%s invert=%s",
            raw_min,
            raw_max,
            invert,
        )

        return ZCalibrationResult(
            raw_bottom=int(raw_min),
            raw_top=int(raw_max),
            raw_min=raw_min,
            raw_max=raw_max,
            invert=invert,
        )

    def auto_calibrate(self, full_reset: bool = False) -> ZCalibrationResult:
        """
        Returns calibration and also writes it to ZSensor.
        """
        if not full_reset:
            return self.default_calibrate()

        try:
            if (not self.actuator.is_connected):
                logger.warning("Z full calibration aborted: actuator is not connected")
                return None
        except Exception as e:
            logger.exception("Z full calibration failed while checking actuator connection: %s", e)
            print(f"Error: actuator is not connected: {e}")
            return None

        # Ensure any background position controller isn't fighting direct motor commands.
        try:
            self.actuator.stop_position_controller()
        except Exception:
            pass

        full_reset_started_at = time.monotonic()

        # Phase 1: drive to bottom first so the full reset naturally finishes at the top.
        raw_bottom = self._move_to_endpoint(
            self.down_cmd,
            phase="seek_bottom",
            min_elapsed_s=self.SEEK_BOTTOM_MIN_DRIVE_S,
            min_travel_raw=self.SEEK_BOTTOM_MIN_TRAVEL_RAW,
        )

        # Phase 2: return from bottom to top and verify the final top reading.
        raw_top = self._return_to_top_and_verify()

        # Guarantee the measured bottom maps to -100 and the measured top maps to +100.
        # If the raw signal increases as we move downward, we need inversion to preserve
        # the public position convention.
        invert = bool(raw_bottom > raw_top)
        raw_min = int(min(raw_bottom, raw_top))
        raw_max = int(max(raw_bottom, raw_top))

        self.actuator.sensor.set_calibration(raw_min=raw_min, raw_max=raw_max, invert=invert)
        self.actuator.invert = bool(self.actuator.sensor.invert)
        self.actuator._save_calibration()
        self._log_phase(
            "save_calibration",
            event="done",
            started_at=full_reset_started_at,
            raw_min=raw_min,
            raw_max=raw_max,
            invert=invert,
        )

        return ZCalibrationResult(
            raw_bottom=int(raw_bottom),
            raw_top=int(raw_top),
            raw_min=int(raw_min),
            raw_max=int(raw_max),
            invert=invert,
        )

