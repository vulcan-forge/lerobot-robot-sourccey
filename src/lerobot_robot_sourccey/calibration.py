"""Calibration-file recovery for Sourccey motor devices."""

import json
import logging
from pathlib import Path

import draccus
from draccus.utils import DecodingError

from lerobot.motors import MotorCalibration

logger = logging.getLogger(__name__)


class CalibrationRecoveryMixin:
    """Treat invalid saved calibration as uncalibrated; preserve filesystem errors."""

    calibration_fpath: Path
    calibration: dict[str, MotorCalibration]

    def _load_calibration(self, fpath: Path | None = None) -> None:
        path = self.calibration_fpath if fpath is None else fpath
        try:
            with path.open(encoding="utf-8") as stream:
                payload = json.load(stream)
            if not isinstance(payload, dict):
                logger.warning("Invalid Sourccey calibration object at %s. Recalibration required.", path)
                self.calibration = {}
                return
            calibration = draccus.decode(dict[str, MotorCalibration], payload)
        except (json.JSONDecodeError, DecodingError, UnicodeError) as exc:
            logger.warning("Invalid Sourccey calibration at %s: %s. Recalibration required.", path, exc)
            self.calibration = {}
        else:
            self.calibration = calibration
