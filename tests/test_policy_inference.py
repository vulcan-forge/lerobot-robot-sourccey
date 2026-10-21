# ruff: noqa: E402
"""Exercise a real CPU ACT policy through upstream inference with a missing arm."""

import numpy as np
import pytest
import torch

inference = pytest.importorskip("lerobot.inference")
if not hasattr(inference, "PolicyRunner"):
    pytest.skip("Requires the LeRobot 0.6.2 inference API", allow_module_level=True)

from lerobot_robot_sourccey.policy_observations import (  # noqa: E402
    ARM_KEYS,
    MissingArmObservations,
)

from lerobot.configs.types import (  # noqa: E402
    FeatureType,
    NormalizationMode,
    PolicyFeature,
)
from lerobot.inference import (  # noqa: E402
    FeatureSpec,
    ObservationSnapshot,
    PolicyRunner,
)
from lerobot.policies.act.configuration_act import ACTConfig  # noqa: E402
from lerobot.policies.act.modeling_act import ACTPolicy  # noqa: E402
from lerobot.policies.act.processor_act import (
    make_act_pre_post_processors,  # noqa: E402
)
from lerobot.utils.constants import ACTION, OBS_ENV_STATE, OBS_STATE  # noqa: E402


@pytest.mark.parametrize("missing", [{"left"}, {"right"}, {"left", "right"}])
def test_configured_missing_arm_pose_passes_real_policy_inference(missing):
    keys = tuple(sorted(set().union(*ARM_KEYS.values())))
    raw = {key: float("nan") if key.split("_", 1)[0] in missing else 5.0 for key in keys}
    adapter = MissingArmObservations({key: 0.0 for key in keys})
    prepared = adapter.observation(raw)
    config = ACTConfig(
        device="cpu",
        chunk_size=2,
        n_action_steps=1,
        use_vae=False,
        dim_model=32,
        n_heads=2,
        dim_feedforward=64,
        n_encoder_layers=1,
        n_decoder_layers=1,
        input_features={
            OBS_STATE: PolicyFeature(type=FeatureType.STATE, shape=(12,)),
            OBS_ENV_STATE: PolicyFeature(type=FeatureType.ENV, shape=(3,)),
        },
        output_features={ACTION: PolicyFeature(type=FeatureType.ACTION, shape=(12,))},
        normalization_mapping={
            kind: NormalizationMode.IDENTITY
            for kind in (FeatureType.STATE, FeatureType.ENV, FeatureType.ACTION)
        },
    )
    runner = PolicyRunner(
        ACTPolicy(config),
        *make_act_pre_post_processors(config),
        action_interval=1 / 30,
        features=(
            FeatureSpec(OBS_STATE, (12,), "float32", names=keys, semantics="normalized Sourccey positions"),
            FeatureSpec(OBS_ENV_STATE, (3,), "float32", semantics="environment state"),
        ),
        action_feature=FeatureSpec(
            ACTION, (12,), "float32", names=keys, semantics="normalized Sourccey positions"
        ),
    )

    def snapshot(observation):
        return ObservationSnapshot(
            {
                OBS_STATE: np.array([observation[key] for key in keys], dtype=np.float32),
                OBS_ENV_STATE: np.zeros(3, dtype=np.float32),
            },
            1.0,
            "move right arm",
        )

    with pytest.raises(ValueError, match="non-finite"):
        runner.predict(snapshot(raw))
    prediction = runner.predict(snapshot(prepared))
    assert torch.isfinite(prediction.canonical_actions).all()
    assert prediction.canonical_actions.shape == (1, 12)
    sent = adapter.action(dict(zip(keys, prediction.canonical_actions[0].tolist(), strict=True)))
    assert not any(key.startswith(f"{arm}_") for arm in missing for key in sent)
