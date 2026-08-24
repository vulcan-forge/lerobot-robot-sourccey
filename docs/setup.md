# Setup

## Requirements

- Python 3.12 or 3.13
- LeRobot 0.6.x
- Sourccey's Linux computer and a controller computer on the same network
- The correct serial ports and device permissions for the leader arms
- [`uv`](https://docs.astral.sh/uv/) on the controller computer

## Install a released profile

On Sourccey's Linux computer:

```bash
uv pip install "lerobot-robot-sourccey[robot] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@0.2.3"
```

On the desktop/controller computer:

```bash
uv pip install "lerobot-robot-sourccey[desktop] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@0.2.3"
```

## Install from PyPI

After a release has been published, add Sourccey to a uv-managed LeRobot
project with:

```bash
uv add "lerobot-robot-sourccey[desktop]"
```

To install it into an already active environment without changing a project:

```bash
uv pip install "lerobot-robot-sourccey[desktop]"
```

On Sourccey's Linux computer, install the hardware dependencies instead:

```bash
uv pip install "lerobot-robot-sourccey[robot]"
```

## Install directly from GitHub

Before the first PyPI release—or when testing an unreleased revision—install
directly from the public repository:

```bash
uv pip install "lerobot-robot-sourccey[desktop] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@main"
```

For repeatable deployments, replace `main` with a release tag such as
`0.2.3`. The robot host can install the same tagged source with the `robot`
extra:

```bash
uv pip install "lerobot-robot-sourccey[robot] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@0.2.3"
```

## Set up from a source checkout

The setup script creates `.venv` with Python 3.12 and installs the selected
profile in editable mode. On a Raspberry Pi, robot setup also installs the
Sourccey udev aliases and performs read-only battery verification when I2C is
available:

```bash
python setup/setup.py robot
```

On the desktop/controller computer:

```bash
python setup/setup.py desktop
```

After the package is installed, the equivalent packaged command is available:

```bash
uv run sourccey-setup robot
uv run sourccey-setup desktop
```

Battery writes are never performed by default. These explicit options are for
initial provisioning or recovery:

```bash
python setup/setup.py robot --configure-battery
python setup/setup.py robot --flash-battery df
python setup/setup.py robot --flash-battery bq
```

Preview operations without changing the environment or hardware:

```bash
python setup/setup.py robot --dry-run
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
