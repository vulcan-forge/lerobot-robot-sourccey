from __future__ import annotations

import base64

from ....protobuf.sourccey_protobuf import SourcceyProtobuf


class RelayCodec:
    def __init__(self) -> None:
        self._converter = SourcceyProtobuf()

    def encode_action(self, command: dict[str, object]) -> tuple[bytes | None, str | None]:
        raw_b64 = command.get("raw_protobuf_b64")
        if isinstance(raw_b64, str) and raw_b64:
            try:
                return base64.b64decode(raw_b64), None
            except Exception:
                return None, "invalid_raw_protobuf_b64"

        action = _action_from_command(command)
        if action is None:
            return None, "invalid_command_payload"

        try:
            proto = self._converter.action_to_protobuf(action)
            return proto.SerializeToString(), None
        except Exception:
            return None, "protobuf_encode_failed"


def _action_from_command(command: dict[str, object]) -> dict[str, float | bool] | None:
    if "action" in command and isinstance(command["action"], dict):
        return dict(command["action"])

    if "input" in command and isinstance(command["input"], dict):
        input_payload = command["input"]
        axes = input_payload.get("axes") if isinstance(input_payload, dict) else {}
        if not isinstance(axes, dict):
            axes = {}
        action: dict[str, float | bool] = {
            "x.vel": float(axes.get("x", 0.0)),
            "y.vel": float(axes.get("y", 0.0)),
            "theta.vel": float(axes.get("theta", 0.0)),
            "untorque_left": False,
            "untorque_right": False,
        }
        if "z" in axes:
            action["z.pos"] = float(axes["z"])
        return action

    chunk = command.get("action_chunk")
    if isinstance(chunk, list) and chunk:
        first = chunk[0]
        if isinstance(first, list):
            values = first
            action = {
                "x.vel": float(values[0]) if len(values) > 0 else 0.0,
                "y.vel": float(values[1]) if len(values) > 1 else 0.0,
                "theta.vel": float(values[2]) if len(values) > 2 else 0.0,
                "untorque_left": False,
                "untorque_right": False,
            }
            if len(values) > 3:
                action["z.pos"] = float(values[3])
            return action

    return None
