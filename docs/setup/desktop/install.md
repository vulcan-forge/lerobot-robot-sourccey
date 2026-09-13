# Install the desktop/controller

## Requirements

- Python 3.12 or 3.13
- LeRobot 0.6.x
- `uv`
- Network access to Sourccey's Linux computer

## Install a released package

```bash
uv pip install "lerobot-robot-sourccey[desktop] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@VERSION_TAG"
```

Replace `VERSION_TAG` with the release used by the robot. Both computers must
use compatible package and protobuf versions.

For a PyPI release:

```bash
uv add "lerobot-robot-sourccey[desktop]"
```

## Install from a source checkout

```bash
python setup/setup.py desktop
```

After the package is installed, the equivalent packaged command is:

```bash
uv run sourccey-setup desktop
```

## Use a local checkout with `lerobot-vulcan`

From the `lerobot-vulcan` repository:

```bash
uv sync --locked
uv pip install -e "../packages/lerobot-robot-sourccey[record,dev]"
```

Verify plugin discovery:

```bash
uv run --no-sync lerobot-teleoperate \
  --robot.type=sourccey_client \
  --teleop.type=sourccey_teleoperator \
  --help
```

Use `--no-sync` with an editable package installation so `uv run` does not
replace it with the version pinned by `lerobot-vulcan`.

Next, configure the [leader-arm ports](leader-arms.md).

Return to the [desktop setup index](README.md).
