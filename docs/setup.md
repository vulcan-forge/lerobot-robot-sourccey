# Setup

## Requirements

- Python 3.12 or 3.13
- LeRobot 0.6.x
- Sourccey's Linux computer and a controller computer on the same network
- The correct serial ports and device permissions for the leader arms
- [`uv`](https://docs.astral.sh/uv/) on the controller computer

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

`--no-sync` prevents `uv run` from reconciling the environment solely against
the LeRobot lockfile after the editable plugin install. On Windows, you can
also invoke `.venv\Scripts\lerobot-teleoperate.exe` directly.

Next, follow [Controlling Sourccey](control.md).

Return to the [documentation index](README.md).
