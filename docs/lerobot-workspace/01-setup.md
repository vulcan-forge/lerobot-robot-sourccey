# Set up Sourccey

Complete the controller setup first, then the robot setup. Python 3.12 or 3.13
and [`uv`](https://docs.astral.sh/uv/getting-started/installation/) are required
on both computers.

## 1. Set up the controller computer

Open a terminal at the root of the `lerobot-vulcan` checkout.

Install the pinned Sourccey desktop profile and the training dependencies:

```bash
uv sync --locked --extra sourccey-desktop --extra training
```

Check that the pinned plugin imports successfully:

```bash
uv run python -c "import importlib.metadata as m; print('Sourccey plugin', m.version('lerobot-robot-sourccey'), 'is installed')"
```

The command should print the installed Sourccey plugin version without a
traceback.

Find the serial port for each leader arm. Run the command once with only the
left arm connected, then once with only the right arm connected:

```bash
uv run lerobot-find-port
```

Record both results. Windows ports look like `COM5`; stable Linux aliases are
normally `/dev/robotLeftArm` and `/dev/robotRightArm`.

Apply the packaged calibration to both leader arms after replacing the example
ports:

```bash
uv run sourccey-teleop-calibrate --left-arm-port=COM5 --right-arm-port=COM6
```

The leader arms do not need to be placed in a calibration pose or stand. This
command applies packaged homing positions and motion ranges; it does not ask
you to move every joint through its range.

The controller is ready when calibration completes without a serial-port
error.

### Developing the plugin locally

The normal path above uses the plugin version pinned in `uv.lock`. If you are
also editing a sibling `lerobot-robot-sourccey` checkout, install it as
editable instead:

```bash
uv pip install -e "../packages/lerobot-robot-sourccey[desktop,dev]"
```

Use `uv run --no-sync` in later commands while that editable install is active;
otherwise `uv` may restore the version pinned by this repository.

## 2. Set up the robot computer

Connect the controller and Sourccey to the same trusted local network. Find the
robot's IP address and SSH credential in its Developer Access or onboarding
screen.

<details>
<summary>Connect to Sourccey over SSH</summary>

Replace `ROBOT_IP` with the address shown on Sourccey, then connect from
Terminal, PowerShell, or another SSH client:

```bash
ssh sourccey@ROBOT_IP
```

On the first connection, compare the host-key fingerprint with the fingerprint
shown by Sourccey before accepting it. Enter the unique password created during
onboarding when prompted. Password input is not shown in the terminal.

After signing in, open the installed LeRobot fork:

```bash
cd ~/Desktop/Projects/sourccey-desktop/modules/lerobot-vulcan
```

Use SSH only on a trusted local network. Do not expose port 22 directly to the
internet. Replace any temporary setup password during onboarding.

</details>

From the `lerobot-vulcan` directory on the robot, install the locked robot-side
dependencies:

Install the pinned robot profile:

```bash
uv sync --locked --extra sourccey-robot
```

This installs the locked robot-side dependencies. It does not change Linux
device rules, battery configuration, or hardware calibration.

Find the robot computer's IP address:

```bash
hostname -I
```

Record the address on the same network as the controller.

### Fresh Linux installation or hardware recovery

Skip this section for a working, factory-prepared Sourccey. If the robot
computer was replaced or stable device aliases are missing, preview and apply
the packaged Linux device rules:

```bash
uv run sourccey-setup robot --dry-run
```

```bash
uv run sourccey-setup robot
```

The setup command installs udev rules and performs read-only battery checks. It
never writes battery configuration unless `--configure-battery` or
`--flash-battery` is explicitly supplied.

Robot calibration is also a recovery procedure, not a normal installation
step. With `sourccey-host` stopped, soft calibration applies the packaged
follower-arm ranges and preserves the current Z limits. No special arm pose is
required:

```bash
uv run sourccey-calibrate
```

Only use a full reset after hardware service when physical arm and Z limits
must be redetected. This command moves hardware, so clear the entire workspace
and keep the emergency stop within reach:

```bash
uv run sourccey-calibrate --full-reset --yes
```

## 3. Start the robot host

On the robot computer, start the host:

```bash
uv run sourccey-host
```

Leave this terminal running. The host is ready when it connects to the robot
hardware and prints `Waiting for commands...`.

Do not use `sourccey-host --help` as an installation check. The host currently
starts connecting to hardware even when `--help` is supplied.

Next: [Teleoperate](02-teleoperate.md).
