# Setup

## Requirements

- Python 3.12 or 3.13
- LeRobot 0.6.x
- Sourccey's Linux computer and a controller computer on the same network
- The correct serial ports and device permissions for the leader arms
- [`uv`](https://docs.astral.sh/uv/) on the controller computer

## Quick install on Sourccey

```bash
uv pip install "lerobot-robot-sourccey[hardware] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@0.2.2"
```

## Install from PyPI

After a release has been published, add Sourccey to a uv-managed LeRobot
project with:

```bash
uv add "lerobot-robot-sourccey[record]"
```

To install it into an already active environment without changing a project:

```bash
uv pip install "lerobot-robot-sourccey[record]"
```

On Sourccey's Linux computer, install the hardware dependencies instead:

```bash
uv pip install "lerobot-robot-sourccey[hardware]"
```

```
uv pip install "lerobot-robot-sourccey[hardware] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@0.2.2"
```

## Install directly from GitHub

Before the first PyPI release—or when testing an unreleased revision—install
directly from the public repository:

```bash
uv pip install "lerobot-robot-sourccey[record] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@main"
```

For repeatable deployments, replace `main` with a release tag such as
`0.2.2`. The robot host can install the same tagged source with the `hardware`
extra:

```bash
uv pip install "lerobot-robot-sourccey[hardware] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@0.2.2"
```

## Install locally with the LeRobot fork

The package does not need to be published. From the LeRobot repository on the
controller computer, install it from its local path:

```powershell
cd C:\Users\Nicholas\Desktop\Projects\Vulcan\lerobot-vulcan
uv sync --locked
uv pip install -e "..\packages\lerobot-robot-sourccey[record,dev]"
```

Verify that LeRobot discovers the plugin:

```powershell
uv run --no-sync lerobot-teleoperate --robot.type=sourccey_client --teleop.type=sourccey_teleoperator --help
```

Use `--no-sync` only for the local editable-install workflow: it prevents
`uv run` from reconciling the environment solely against the LeRobot lockfile.
For a normal `uv add` installation, use `uv run` without `--no-sync`. On
Windows, you can also invoke `.venv\Scripts\lerobot-teleoperate.exe` directly.

Next, follow [Controlling Sourccey](control.md).

Return to the [documentation index](README.md).
