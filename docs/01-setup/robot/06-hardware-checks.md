# Sourccey Hardware Checks

## TL;DR

Swap `192.168.1.237` for your robot's IP. Exit code 0 = everything passed.

The live views open in your **browser**, not a window: this package uses
`opencv-python-headless`, so `cv2.imshow` cannot draw. Each camera check prints a
`http://127.0.0.1:8091/`-style URL — open it while the check runs.

The camera checks run **until you press Ctrl+C** (that is when the results table prints).
While running they print a `live  front_left=28.4fps ...` heartbeat every 2s, so you can
see data flowing without opening the browser. Add `--seconds N` to time-box a run, or
`--view none --seconds 10` for a straight pass/fail with no preview at all.

**From your PC** — needs `sourccey-host` running on the Pi, nothing else connected:

```bash
# eye cameras + bottom: live view of front_left, front_right, bottom
uv run --no-sync sourccey-check-eye-cameras --remote-ip 192.168.1.249
#   ^ bottom FAILs until it is added to sourccey_cameras_config(); until then check it
#     on the Pi with sourccey-check-bottom-camera (below), or add --skip-bottom here

# arm cameras: live view of wrist_left + wrist_right
uv run --no-sync sourccey-check-arm-cameras --remote-ip 192.168.1.237

# all 12 joints + Z + wheels, as the host reads them
uv run --no-sync sourccey-check-motors --remote-ip 192.168.1.237
```

**On the Pi** (`ssh`) — stop the host first, these need the devices:

```bash
# eye cameras, opened directly (add --include-bottom for the underside one)
uv run --no-sync sourccey-check-eye-cameras-local

# arm cameras, opened directly
uv run --no-sync sourccey-check-arm-cameras-local

# arm servos 1-12 pinged by ID, with voltage + temp; wheel driver pins; Z actuator ADC
uv run --no-sync sourccey-check-motors

# lidar spin + returns, then IMU accel/gyro/mag
uv run --no-sync sourccey-check-lidar-imu

# bottom camera: unplug it when asked, and the script learns which device it is
uv run --no-sync sourccey-check-bottom-camera --identify

# ...and give it a permanent /dev/cameraFrontBottom name like the other four (needs sudo)
uv run --no-sync sourccey-check-bottom-camera --identify --name-it

# audit all camera names: present, unique, unchanged, and surviving a reboot
uv run --no-sync sourccey-check-bottom-camera --verify-names

# confirm the wheel motors themselves spin (wheels OFF the ground, asks first)
uv run --no-sync sourccey-check-motors --skip-arms --skip-z --wiggle

# linear actuator: drive it both ways, confirm the ADC follows (needs clearance, asks first)
uv run --no-sync sourccey-check-motors --skip-arms --skip-wheels --z-stroke
```

**No-preview versions** for a quick pass/fail with saved frames:

```bash
uv run --no-sync sourccey-check-eye-cameras --remote-ip 192.168.1.249 \
  --view none --seconds 10 --save-dir camera_health
uv run --no-sync sourccey-check-arm-cameras --remote-ip 192.168.1.249 \
  --view none --seconds 10 --save-dir camera_health
```

Gotchas in one line each: `bottom` isn't in the default configuration's `sourccey_cameras_config()` yet, so
the host never publishes it and the check FAILs it (that FAIL is real — the camera is not
reaching the robot's software at all); run camera checks with teleop closed or you both get
half the frames; the wheels have no encoders, so only `--wiggle` proves a wheel motor is alive.

## Pre-ship checklist (all on the Pi)

Everything below runs over SSH on the robot, in order. Stop `sourccey-host` first — the
first three need exclusive access to the devices.

```bash
# 1. cameras: two eyes, two wrists, and the underside one
uv run --no-sync sourccey-check-eye-cameras-local --include-bottom
uv run --no-sync sourccey-check-arm-cameras-local

# 2. electrical roll-call: 12 servos with voltage + temp, wheel driver pins, Z ADC
uv run --no-sync sourccey-check-motors

# 3. sensors
uv run --no-sync sourccey-check-lidar-imu

# 4. camera names are permanent (run again after a reboot)
uv run --no-sync sourccey-check-bottom-camera --verify-names

# 5. things that MOVE - robot on blocks, wheels off the ground
uv run --no-sync sourccey-check-motors --skip-arms --skip-z --wiggle
uv run --no-sync sourccey-check-motors --skip-arms --skip-wheels --z-stroke
```

Every one exits non-zero if anything failed, so `&&` them together if you want a single
go/no-go. Open the saved frames in `camera_health/` before calling it done — that is the
only check that the cameras are pointed where you think they are.

Finish by rebooting the robot and re-running step 4: that is the real proof the udev names
survive a power cycle.

---

Seven scripts answer "is everything on the robot actually working?" — the eye cameras, the
arm cameras, the underside camera, the LiDAR and IMU, and an electrical roll-call of the 12
arm servos, the wheel drivers, and the Z actuator.

Two of them run **from your control PC** and connect to the robot the way the teleop
client does (the host's observation stream). The rest run **on the Pi**, because they touch
devices the host does not publish to the network.

| Script                             | Checks                                   | Runs on                    | Needs                      |
| ---------------------------------- | ---------------------------------------- | -------------------------- | -------------------------- |
| `sourccey-check-eye-cameras`       | `front_left`, `front_right`, `bottom`    | your PC                    | `sourccey-host` running    |
| `sourccey-check-arm-cameras`       | `wrist_left`, `wrist_right`              | your PC                    | `sourccey-host` running    |
| `sourccey-check-eye-cameras-local` | the same eyes, opened directly           | the Pi                     | host **stopped**           |
| `sourccey-check-arm-cameras-local` | the same wrists, opened directly         | the Pi                     | host **stopped**           |
| `sourccey-check-motors`            | 12 arm servos, wheel drivers, Z actuator | the Pi (PC mode available) | host **stopped** on the Pi |
| `sourccey-check-lidar-imu`         | LiDAR scans, I2C IMU                     | the Pi                     | —                          |
| `sourccey-check-bottom-camera`     | the underside camera, straight off V4L2  | the Pi                     | —                          |

Shared plumbing lives in `lerobot_robot_sourccey.diagnostics.camera_remote` (PC-side, ZMQ + protobuf) and
`lerobot_robot_sourccey.diagnostics.camera_devices` (Pi-side, direct V4L2).

### Installation

All checks are installed with the Sourccey package; a LeRobot source checkout is
not required. On the robot, install `lerobot-robot-sourccey[robot]`; on the
controller, install `lerobot-robot-sourccey[desktop]`.

```bash
uv pip install "lerobot-robot-sourccey[robot]"
uv run --no-sync sourccey-check-motors --help
```

For local development, install this checkout editably into the environment:
`uv pip install -e "../packages/lerobot-robot-sourccey[robot]"` from the LeRobot
workspace. Use `uv run --no-sync` until the release pin includes these commands.

Camera paths, motor models, GPIO pins, and lift duty defaults come from package
configuration. The bottom camera uses the packaged `/dev/cameraFrontBottom`
udev alias. Direct camera checks report failed reads without auto-recovery;
they test the device's health rather than masking faults with retrying frames.
The motor check uses the package retry policy, and the combined sensor check
uses the package's CRC-validating LiDAR parser and IMU backend.

## Table of Contents

1. [Why some checks are PC-side and some are not](#why-some-checks-are-pc-side-and-some-are-not)
2. [1) Eye + Bottom Cameras (from your PC)](#1-eye--bottom-cameras-from-your-pc)
3. [2) Arm Cameras (from your PC)](#2-arm-cameras-from-your-pc)
4. [3) Motor Roll-Call (on the Pi)](#3-motor-roll-call-on-the-pi)
5. [4) LiDAR + IMU (on the Pi)](#4-lidar--imu-on-the-pi)
6. [Reading the Results](#reading-the-results)
7. [Run Everything in One Pass](#run-everything-in-one-pass)
8. [Troubleshooting](#troubleshooting)

---

## Why some checks are PC-side and some are not

`sourccey-host` publishes exactly one thing to the network: the observation stream
on `tcp://<pi-ip>:5556`, carrying arm joint positions, base velocity, Z position, and
**camera frames**. That is what the teleop client subscribes to, and it is what the two
camera checks subscribe to as well — passively, observations only, never the command
socket, so they cannot move the robot.

The LiDAR (serial), the IMU (I2C), and the motor buses themselves are **not** published
by the host. There is no stream for a PC-side client to read, so those checks SSH-and-run
on the Pi. `sourccey-check-motors` does have a `--remote-ip` mode, but it can only
report what the host is reading, not perform a bus-level roll-call — see below.

> **One client at a time.** The host's observation socket is a ZMQ PUSH, which
> round-robins between connected receivers. If teleop is running while you check the
> cameras, the two of you split the frames and both look slow. Run the checks alone.

## 1) Eye + Bottom Cameras (from your PC)

```bash
# watch the feeds live
uv run --no-sync sourccey-check-eye-cameras --remote-ip 192.168.1.237

# unattended: 15 seconds, no viewer, one saved frame per camera
uv run --no-sync sourccey-check-eye-cameras --remote-ip 192.168.1.237 \
  --view none --seconds 15 --save-dir camera_health
```

Expects `front_left`, `front_right`, and `bottom`.

> **Note:** `bottom` is not in the default configuration's `sourccey_cameras_config()`, so the host does
> not open it and it never reaches the observation stream. That FAIL is accurate — the
> camera is not reaching the robot's software at all — but it says nothing about the
> camera itself. Check the hardware with
> [`sourccey-check-bottom-camera`](#bottom-camera-on-the-pi-standalone) instead, and
> pass `--skip-bottom` here for a clean two-camera run in the meantime.
> (`--bottom-key <name>` covers the case where the host publishes it under another name.)

### Bottom camera, on the Pi (standalone)

Until the host opens it, check the underside camera by going straight to the V4L2 device:

```bash
# unplug test - the reliable way to identify it
uv run --no-sync sourccey-check-bottom-camera --identify

# auto: works when exactly one USB camera is unaccounted for
uv run --no-sync sourccey-check-bottom-camera

# you already know which node it is
uv run --no-sync sourccey-check-bottom-camera --device /dev/video8

# just show the USB cameras and which the robot already claims
uv run --no-sync sourccey-check-bottom-camera --list

# watch it live from your PC (the Pi is headless)
uv run --no-sync sourccey-check-bottom-camera --identify --view mjpeg
```

**`--identify` is the one to use when in doubt.** It lists the connected USB cameras, asks
you to unplug the bottom one, sees which device vanished, asks you to plug it back in, and
then checks it. It refuses to guess if nothing disappeared or if several devices did.

Identification is not as simple as "scan `/dev/video*`": a Pi 5 exposes around thirty V4L2
nodes, and most are internal ISP and codec devices. Opening those does not fail — it blocks
for ten seconds a time in `select()`. So candidates are filtered first, before anything is
opened:

- the node's sysfs `device` link must resolve under a **USB** device (this drops the Pi's
  `rp1-cfe`/`pispbe`/codec nodes), and
- `index` must be **0** — a UVC camera also registers an index-1 metadata node, which
  opens successfully and then never delivers a frame.

Once the camera is found, the check reports the negotiated resolution/format/frame rate,
applies the same blank-frame and frozen-feed checks as the other camera checks, and saves
`camera_health/bottom.jpg` so you can confirm it is really looking at the floor.

On success it prints exactly what to put in the config later: the `/dev/v4l/by-path/...`
name (stable, unlike `/dev/videoN`, which can change on the very next re-plug — `--identify`
will tell you when it does).

#### Giving it a permanent name

`--name-it` finishes the job: it installs a udev rule so the camera comes up as
`/dev/cameraFrontBottom`, exactly like the other four.

```bash
uv run --no-sync sourccey-check-bottom-camera --identify --name-it
```

The rule is keyed to the camera's **USB port** (`KERNELS=="1-1.2.1"`), not its serial or
vendor id, because all five cameras are the same Innomaker model — where it is plugged in is
the only thing that distinguishes them. Consequence worth knowing: move the camera to a
different port and the name follows the _port_, not the camera. Re-run `--name-it` if you
re-cable the robot.

What it does, in order: appends to whichever rules file already names the other cameras
(falling back to `/etc/udev/rules.d/99-sourccey-cameras.rules`), backs that file up first,
reloads and triggers udev, then verifies `/dev/cameraFrontBottom` really resolves to the camera on
that port. It needs `sudo` and shows you the exact line before writing anything.

Guard rails: it only runs after the stream check passes (no naming a broken camera), it never
rewrites or removes existing rules, it is a no-op if the same rule is already present, and if
a `cameraFrontBottom` rule exists for a _different_ port it stops and tells you to resolve that by
hand. `--symlink-name` and `--rules-file` override the defaults.

#### Verifying nothing else moved

Adding a rule can, in principle, disturb the other four names — and a `/dev` entry that works
right now tells you nothing about whether it comes back after a power cycle. So `--name-it`
audits itself afterwards, and the same audit is available standalone:

```bash
# changes nothing; safe to run any time, especially after a reboot
uv run --no-sync sourccey-check-bottom-camera --verify-names
```

What it checks:

**Nothing else changed.** The rules file is re-read and compared against what it contained
before: every pre-existing line must be byte-for-byte identical, and the only new content must
be exactly the lines that were meant to be added. It also snapshots where each camera name
pointed _before_ the change and compares afterwards — a name that vanished, or that now
resolves to a **different USB port**, is a FAIL. A changed `/dev/videoN` number with the same
port is fine, and is reported as such: the name is still following the same physical camera.

**The names are permanent, not temporary.** Three independent signals, because "it works now"
is exactly what a hand-made symlink also looks like:

1. the rule is in a persistent directory — a rule under `/run` or `/tmp` is a FAIL, since it
   would be gone after a power cycle — and the filename ends in `.rules`, which is the only
   thing udev reads;
2. udev's own database lists the symlink for that device (`udevadm info --query=symlink`), so
   udev created it from a rule rather than someone having made a symlink by hand;
3. replaying the device event (`udevadm test`) reproduces the symlink — the same thing that
   will happen on the next boot.

`--verify-names` also flags two names resolving to the same USB port, which is how a
duplicated rule turns into cameras swapping identities after a reboot.

If anything fails, the previous rules file is sitting next to it as `.bak`, and the output
says to resolve it before rebooting.

Naming the device does not by itself put the camera in the robot's observation stream — that
still needs `bottom` added to `sourccey_cameras_config()`, at which point
`index_or_path="/dev/cameraFrontBottom"` is the value to use.

Useful flags: `--scale 3` to zoom the 320x240 frames, `--seconds N` to time-box the run,
`--view none` to skip the preview entirely.

The preview is served over HTTP (the check prints the URL) because this package uses
`opencv-python-headless`, which has no `imshow`. `--view window` therefore fails with an
explanation rather than a traceback; it only works if you install the GUI build
(`uv pip install opencv-python`) in a separate environment.

### The same cameras, checked on the Pi

```bash
# on the Pi, host stopped
uv run --no-sync sourccey-check-eye-cameras-local
uv run --no-sync sourccey-check-eye-cameras-local --include-bottom
uv run --no-sync sourccey-check-arm-cameras-local
```

These open `/dev/cameraFrontLeft` and friends directly. Use them when the remote check
reports something bad, because they answer the question it cannot: **is the camera broken,
or did the host simply not open it?** Over the observation stream those look identical — a
missing key, or black frames the host substituted after a failed read.

Same verdicts as the remote checks (blank, frozen, low fps), plus open failures naming the
likely cause. `--view mjpeg` serves the tiled preview so you can watch from your PC while it
runs, `--seconds 0` runs until Ctrl+C, and `--device front_left=/dev/video6` overrides a path.

The direct checks open the devices without starting the robot host. Device names
and capture settings come from the package's camera configuration; CLI overrides
can target another V4L2 device while diagnosing wiring or naming faults.

## 2) Arm Cameras (from your PC)

```bash
uv run --no-sync sourccey-check-arm-cameras --remote-ip 192.168.1.237
```

Expects `wrist_left` and `wrist_right`. It never commands the arms — move them by hand
if you want to confirm the view is live; the check also flags frozen feeds on its own.
Its browser port defaults to **8092** (the eye check uses **8091**), so both previews can
run at once.

## 3) Motor Roll-Call (on the Pi)

The electrical check: SSH into the Pi, stop `sourccey-host` (it holds the serial buses
and the GPIO), and run:

```bash
uv run --no-sync sourccey-check-motors
```

**Arm servos** — pings every expected ID on both buses and reports each servo's model,
bus voltage, temperature, and raw position:

```
left  arm  /dev/robotLeftArm   IDs 1-6     right arm  /dev/robotRightArm  IDs 7-12
order: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper
```

A servo that does not answer is reported as `SILENT`. The bus roll-call also lists any
**unexpected** IDs, which is how you catch a duplicate or misassigned servo ID. Nothing is
written to any servo: the bus is opened without a handshake and closed without touching
torque.

**Wheel drivers** — claims each DRV8874 IN1/IN2 GPIO pin and holds it idle, proving the
pins are valid, free, and drivable. Be aware of what this cannot tell you: the DC motors
are **open-loop** — no encoders, no current sensing anywhere in the stack — so a wheel
motor unplugged at the H-bridge looks identical to a healthy one from software. To confirm
the motors themselves:

```bash
# briefly pulses each wheel; asks for confirmation first
uv run --no-sync sourccey-check-motors --skip-arms --skip-z --wiggle
```

Put the robot on blocks with its wheels off the ground first. The linear actuator is
excluded unless you add `--wiggle-actuator`.

**Z actuator (linear actuator)** — two levels. The default run reads the potentiometer
through the MCP3008 ADC and warns when the value is pinned at a rail (usually a
disconnected wiper rather than an end stop). That proves the sensor, not the motor.

For the full closed-loop check — the only one on the robot, since Z is the one axis with
feedback — add `--z-stroke`:

```bash
uv run --no-sync sourccey-check-motors --skip-arms --skip-wheels --z-stroke
```

It asks for confirmation, then drives the column one way and back while sampling the ADC,
and passes only if the reading actually moved (`--z-min-delta`, 15 raw counts by default).
A single pass therefore covers the H-bridge, the motor, the mechanism, the potentiometer,
and the ADC. Notes:

- Give the column clearance above and below, and keep arms and cables clear.
- It stops early if the ADC hits a rail, so it will not grind into an end stop. If the
  column was already parked at one, reposition it and re-run.
- `--z-duty` defaults to the configured `z_minimum_up_command` (0.82). Below that the
  actuator will not overcome stiction, which is why the generic `--wiggle` duty leaves it
  out unless you pass `--wiggle-actuator`.
- Getting movement in only one direction is a WARN, not a PASS: one side may be blocked,
  at an end stop, or miswired.

**PC-side mode** shows what the host is currently reading for all 12 joints, Z, and the
base velocities:

```bash
uv run --no-sync sourccey-check-motors --remote-ip 192.168.1.237
```

Treat it as a smoke test, not a roll-call: a servo that dropped off the bus can still
show its last value, and the base velocities are commanded numbers, not measurements.

## 4) LiDAR + IMU (on the Pi)

```bash
# both checks: 5s of LiDAR, 3s of IMU
uv run --no-sync sourccey-check-lidar-imu

# LiDAR only, longer listen, different port
uv run --no-sync sourccey-check-lidar-imu --skip-imu \
  --lidar-port /dev/ttyUSB1 --lidar-seconds 10

# IMU only, plus an interactive yaw test
uv run --no-sync sourccey-check-lidar-imu --skip-lidar --spin-test
```

**LiDAR** — opens the serial port briefly, parses LD06/LD19 packets, and reports packets
received, valid returns, spin rate in RPM, angular coverage of the 360° circle, and
min/median/max distance. It fails if no data arrives, if the rotor is below ~120 RPM
(stalled or unpowered), or if no point clears the confidence threshold; it warns if
angular coverage is under 70%, which means something is blocking the rotor. The port is
released as soon as the check ends.

**IMU** — reads the LSM6DSOX + LIS3MDL over I2C and reports sample rate, accelerometer
magnitude (should sit near 9.81 m/s² at rest), gyro rates, and magnetometer field
strength. It fails if the driver cannot connect, if `|accel|` is nowhere near gravity, or
if every sample is byte-identical — a wedged I2C read looks "successful" but is not live
data.

**`--spin-test`** is interactive: press Enter, rotate the robot ~90° by hand, and the
script integrates the yaw gyro and confirms it tracked the rotation.

## Reading the Results

Every run ends with a summary, and the exit code is `0` only if nothing failed:

```
[check] ==== Sourccey eye + bottom cameras: results ====
[check] 412 observation packets received from 192.168.1.237
[check] cameras the host is publishing: front_left, front_right, wrist_left, wrist_right
[check] PASS front_left   412 frames at 29.8 fps
[check] WARN front_right  only 11.2 fps (host camera is configured for 30); ...
[check] FAIL bottom       the host published no frames for this camera ...
[check] 2/3 cameras healthy
```

- **PASS** — present and behaving.
- **WARN** — working but degraded: below half the configured frame rate, a hot servo, a
  LiDAR with thin angular coverage.
- **FAIL** — absent, silent, or delivering data that is not real: a camera publishing
  blank or frozen frames, a servo that does not answer its ID, a stalled LiDAR rotor.

### Why "PASS at 30 fps" is not enough on its own

When a camera read fails on the robot, `Sourccey.get_observation()` does **not** drop the
camera from the observation — it substitutes `np.zeros(...)` to keep the schema stable, and
logs a warning on the Pi. A completely dead camera therefore keeps arriving at full frame
rate; only its content is empty. Frame count and fps alone would call that healthy.

So every camera verdict also inspects pixels:

- **all frames black/flat** → FAIL, named as host-substituted blank frames.
- **some frames black** → WARN with the count, which is what an intermittently failing
  camera (loose USB, marginal power) looks like.
- **frames identical to their predecessor** → the feed is stalling and republishing its
  last buffer; >90% is a FAIL, any at all is a WARN.

A clean pass prints `(0 blank, 0 frozen)` so you can see the check actually ran. Saved
frames from `--save-dir` are the final confirmation — open them and check the camera is
pointed where you think it is.

## Run Everything in One Pass

From your PC, with the host running:

```bash
uv run --no-sync sourccey-check-eye-cameras --remote-ip 192.168.1.237 \
  --view none --seconds 10 --save-dir camera_health --skip-bottom
uv run --no-sync sourccey-check-arm-cameras --remote-ip 192.168.1.237 \
  --view none --seconds 10 --save-dir camera_health
```

Then on the Pi, with the host stopped:

```bash
uv run --no-sync sourccey-check-motors
uv run --no-sync sourccey-check-lidar-imu
```

Any non-zero exit code means something on that list is not working.

## Troubleshooting

| Symptom                                         | Likely cause / fix                                                                                                                                                                                          |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `no observation packet from tcp://...:5556`     | The host is not running or the IP is wrong. Start it on the Pi: `uv run sourccey-host`.                                                                                                                     |
| Camera reports `NOT PUBLISHED`                  | The host did not open that camera — it is missing from `sourccey_cameras_config()`, or it failed to connect on the Pi. Check the host's console for camera warnings.                                        |
| All cameras at half frame rate                  | Another client (teleop, a recording session) is sharing the observation stream.                                                                                                                             |
| Every frame is blank                            | Lens cap, dead exposure, or the camera opened but never streamed. Swap ports/cables with a known-good camera to separate hardware from mapping. See [Robot devices](02-devices.md) for device-level checks. |
| Servo reports `SILENT`                          | That ID is not answering: check the daisy-chain cable upstream of it, its power rail, and whether its ID was reassigned.                                                                                    |
| `unexpected IDs on this bus`                    | Two servos share an ID, or one was flashed with the wrong ID.                                                                                                                                               |
| `LOW VOLTAGE` on several servos                 | The pack is sagging under load — check the battery and the power wiring, not the servos.                                                                                                                    |
| `could not claim its pins`                      | Another process (usually `sourccey-host`) already owns that GPIO. Stop it and retry.                                                                                                                        |
| `cv2.imshow ... function is not implemented`    | An old copy of the scripts. The package uses `opencv-python-headless` (no `imshow`); current versions serve the preview over HTTP instead and print the URL.                                                |
| `--z-stroke`: ADC moved at most N counts        | The column is not moving (check the actuator's H-bridge and power) or the pot is not tracking it. If it was parked at an end stop, reposition and re-run.                                                   |
| `--z-stroke`: moved, but not in both directions | One direction is blocked, at an end stop, or miswired at the H-bridge.                                                                                                                                      |
| `no such serial device: /dev/lidarFront`        | Run `ls -l /dev/ttyUSB* /dev/ttyACM*` and pass the right `--lidar-port`.                                                                                                                                    |
| LiDAR `spin rate 0.0 rpm`                       | The rotor is not turning — check LiDAR power; some hubs cannot supply it from the data line alone.                                                                                                          |
| IMU `could not connect`                         | Run `i2cdetect -y 1`; expect `0x6a` (LSM6DSOX) and `0x1c` (LIS3MDL). Enable I2C in `raspi-config`, and install extras with `uv sync --locked --extra sourccey-robot`.                                       |
| IMU `every sample is identical`                 | The I2C read is wedged. Power-cycle the Pi; if it persists, check the IMU wiring and pull-ups.                                                                                                              |

Related: [Robot devices](02-devices.md) for device-name and v4l2-level camera
checks on the Pi, [Battery](03-battery.md) for pack telemetry, and
[Robot host](05-host.md) for starting the host and teleop.
