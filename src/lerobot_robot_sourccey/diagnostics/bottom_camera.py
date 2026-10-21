#!/usr/bin/env python3
"""Find and check the underside (bottom) camera - run this ON THE PI.

The bottom camera is not in `sourccey_cameras_config()` yet, so the host never
opens it and it never reaches the observation stream. This script goes straight
to the V4L2 device instead.

Identifying it is the hard part, because a Pi 5 exposes ~30 `/dev/videoN` nodes
and most are internal ISP/codec devices, not cameras. Two ways to cut through
that:

    # 1) unplug test - the reliable one. Lists USB cameras, asks you to unplug
    #    the bottom camera, sees which one vanished, asks you to plug it back in,
    #    then checks it and prints its STABLE device path.
    uv run --no-sync sourccey-check-bottom-camera --identify

    # ...and give it a permanent /dev/cameraFrontBottom name like the other four
    # (writes a udev rule keyed to its USB port; asks first, needs sudo)
    uv run --no-sync sourccey-check-bottom-camera --identify --name-it

    # audit every camera name: present, unique, unchanged, and reboot-proof.
    # Changes nothing - run it any time, especially after a reboot.
    uv run --no-sync sourccey-check-bottom-camera --verify-names

    # 2) auto - assumes the only USB camera that is not one of the four
    #    configured /dev/camera* devices is the bottom one.
    uv run --no-sync sourccey-check-bottom-camera

    # you already know the device
    uv run --no-sync sourccey-check-bottom-camera --device /dev/video8

    # what USB cameras exist and which are spoken for
    uv run --no-sync sourccey-check-bottom-camera --list

    # watch it live in a browser on your PC (the Pi is headless)
    uv run --no-sync sourccey-check-bottom-camera --view mjpeg

Only real USB capture nodes are ever opened: candidates are filtered by their
sysfs device path (must sit under a USB device) and by `index == 0` (a UVC camera
also exposes an index-1 metadata node that blocks for 10s per read attempt).
That is what made blind probing take minutes.

Every run saves a frame so you can eyeball what the camera actually sees.
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

from .preview import MjpegServer, gui_available, lan_ip

V4L_SYSFS = "/sys/class/video4linux"
# The four cameras the robot already claims; whatever USB camera is left over is
# the interesting one.
KNOWN_CAMERA_LINKS = (
    "/dev/cameraFrontLeft",
    "/dev/cameraFrontRight",
    "/dev/cameraWristLeft",
    "/dev/cameraWristRight",
)
# A frame flatter than this is a blank sensor output, not a picture.
BLANK_FRAME_STD = 1.5


@dataclass
class VideoDevice:
    """One /dev/videoN node, with the sysfs facts needed to judge it."""

    node: str
    name: str
    is_usb: bool
    index: int
    usb_port: str | None
    by_path: str | None
    by_id: str | None

    @property
    def is_capture(self) -> bool:
        """True for the node that actually delivers frames.

        A UVC camera registers two nodes: index 0 is video capture, index 1 is
        the metadata stream. Opening the metadata node succeeds and then blocks
        in select() until it times out, which is what made the old blind probe
        crawl.
        """
        return self.is_usb and self.index == 0

    @property
    def stable_path(self) -> str:
        """The path worth writing into a config: /dev/videoN moves on re-plug."""
        return self.by_path or self.by_id or self.node

    def describe(self) -> str:
        port = f" port={self.usb_port}" if self.usb_port else ""
        return f"{self.node:<14} {self.name[:34]:<34}{port}"


def _read_sysfs(node_name: str, attr: str) -> str:
    try:
        with open(os.path.join(V4L_SYSFS, node_name, attr)) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _symlink_map(directory: str) -> dict[str, str]:
    """Map each /dev/videoN to a stable udev symlink pointing at it."""
    mapping: dict[str, str] = {}
    for link in glob.glob(os.path.join(directory, "*")):
        try:
            mapping.setdefault(os.path.realpath(link), link)
        except OSError:
            continue
    return mapping


def enumerate_devices() -> list[VideoDevice]:
    """Describe every V4L2 node on this machine."""
    by_path = _symlink_map("/dev/v4l/by-path")
    by_id = _symlink_map("/dev/v4l/by-id")

    devices: list[VideoDevice] = []
    for sysfs_entry in sorted(glob.glob(os.path.join(V4L_SYSFS, "video*"))):
        node_name = os.path.basename(sysfs_entry)
        node = f"/dev/{node_name}"
        if not os.path.exists(node):
            continue
        # The `device` symlink points into the bus the node hangs off; a USB
        # camera resolves to something containing /usb, while the Pi's ISP and
        # codec nodes resolve to platform devices.
        device_link = os.path.join(sysfs_entry, "device")
        real = os.path.realpath(device_link) if os.path.exists(device_link) else ""
        is_usb = "/usb" in real
        usb_port = os.path.basename(real).split(":")[0] if is_usb else None
        index_text = _read_sysfs(node_name, "index")
        devices.append(
            VideoDevice(
                node=node,
                name=_read_sysfs(node_name, "name") or "(unknown)",
                is_usb=is_usb,
                index=int(index_text) if index_text.isdigit() else -1,
                usb_port=usb_port,
                by_path=by_path.get(node),
                by_id=by_id.get(node),
            )
        )
    return devices


def claimed_nodes() -> dict[str, str]:
    """Map each /dev/videoN the robot already uses to its configured name."""
    claimed = {}
    for link in KNOWN_CAMERA_LINKS:
        if os.path.exists(link):
            claimed[os.path.realpath(link)] = link
    return claimed


def usb_cameras() -> list[VideoDevice]:
    return [d for d in enumerate_devices() if d.is_capture]


def print_inventory() -> list[VideoDevice]:
    """Show the USB cameras and who owns them; return the unclaimed ones."""
    claimed = claimed_nodes()
    cameras = usb_cameras()

    print("[bottom] configured cameras:")
    for link in KNOWN_CAMERA_LINKS:
        target = os.path.realpath(link) if os.path.exists(link) else None
        print(f"[bottom]   {link:<24} -> {target or 'MISSING'}")

    print(f"[bottom] USB capture devices found: {len(cameras)}")
    unclaimed = []
    for device in cameras:
        owner = claimed.get(device.node)
        tag = f"claimed by {os.path.basename(owner)}" if owner else "UNCLAIMED"
        print(f"[bottom]   {device.describe()}  {tag}")
        if owner is None:
            unclaimed.append(device)

    total_nodes = len(enumerate_devices())
    print(
        f"[bottom] (ignored {total_nodes - len(cameras)} non-USB / metadata V4L2 nodes - "
        "those are the Pi's internal ISP and codec devices)"
    )
    return unclaimed


def identify_by_unplug(args: argparse.Namespace) -> VideoDevice | None:
    """Ask the operator to unplug the camera, and see which device disappears."""
    print("[bottom] ---- identify by unplug ----")
    before = {d.node: d for d in usb_cameras()}
    if not before:
        print("[bottom] FAIL  no USB cameras are enumerating at all - check the hub and cabling")
        return None
    print(f"[bottom] {len(before)} USB camera(s) currently connected:")
    for device in before.values():
        print(f"[bottom]   {device.describe()}")

    print()
    input("[bottom] Now UNPLUG the bottom camera, then press Enter... ")

    # udev can take a moment to tear the nodes down after the physical unplug.
    missing: list[VideoDevice] = []
    deadline = time.monotonic() + args.settle_seconds
    while time.monotonic() < deadline:
        current = {d.node for d in usb_cameras()}
        missing = [d for node, d in before.items() if node not in current]
        if missing:
            break
        time.sleep(0.3)

    if not missing:
        print(f"[bottom] FAIL  nothing disappeared after {args.settle_seconds:.0f}s")
        print("[bottom]       either the camera was not unplugged, or it is on a hub that keeps")
        print("[bottom]       the node alive - try unplugging at the camera end")
        return None
    if len(missing) > 1:
        print(
            f"[bottom] FAIL  {len(missing)} devices disappeared at once: {', '.join(d.node for d in missing)}"
        )
        print("[bottom]       unplug ONLY the bottom camera and re-run")
        return None

    found = missing[0]
    print(f"[bottom] {found.node} disappeared - that is the bottom camera")
    if found.usb_port:
        print(f"[bottom] it lives on USB port {found.usb_port}")

    print()
    input("[bottom] Plug it back in, then press Enter... ")

    # The node NUMBER can change across a re-plug, so match on the physical USB
    # port instead - that is the thing that stays put.
    deadline = time.monotonic() + args.settle_seconds
    while time.monotonic() < deadline:
        for device in usb_cameras():
            if found.usb_port and device.usb_port == found.usb_port:
                if device.node != found.node:
                    print(
                        f"[bottom] it came back as {device.node} (the node number changed - "
                        "this is exactly why a by-path name is worth using)"
                    )
                else:
                    print(f"[bottom] {device.node} is back")
                return device
            if device.node == found.node:
                print(f"[bottom] {device.node} is back")
                return device
        time.sleep(0.3)

    print(f"[bottom] FAIL  it did not come back within {args.settle_seconds:.0f}s")
    print("[bottom]       re-seat the connector and re-run")
    return None


def probe(device: str, args: argparse.Namespace) -> cv2.VideoCapture | None:
    """Open one device and return the capture if it yields a real frame."""
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        return None
    if args.fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Some UVC cameras hand back one empty frame while the stream spins up.
    for _ in range(5):
        ok, frame = cap.read()
        if ok and frame is not None:
            return cap
        time.sleep(0.1)
    cap.release()
    return None


def stream_check(device: str, args: argparse.Namespace) -> int:
    """Sample the chosen device and judge whether it is really working."""
    cap = probe(device, args)
    if cap is None:
        print(f"[bottom] FAIL  {device} opened but produced no frame (is another process using it?)")
        return 1

    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc = "".join(chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)).strip()
    print(
        f"[bottom] negotiated {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
        f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} @ {cap.get(cv2.CAP_PROP_FPS):.0f} "
        f"fps {fourcc or '????'}"
    )

    server: MjpegServer | None = None
    if args.view == "mjpeg":
        server = MjpegServer(args.http_port, f"Sourccey bottom camera ({device})")
        server.start()
        print(f"[bottom] open http://{lan_ip()}:{args.http_port}/ on your PC to watch it")
    elif args.view == "window":
        print("[bottom] press 'q' in the preview window to stop")

    frames = failures = blank = frozen = 0
    previous_checksum = None
    last_frame = None
    stamps: list[float] = []
    start = time.monotonic()
    try:
        while (time.monotonic() - start) < args.seconds:
            ok, frame = cap.read()
            if not ok or frame is None:
                failures += 1
                time.sleep(0.02)
                continue
            frames += 1
            stamps.append(time.monotonic())
            last_frame = frame
            checksum = int(frame[::8, ::8].sum())
            if previous_checksum is not None and checksum == previous_checksum:
                frozen += 1
            previous_checksum = checksum
            if float(frame.std()) < BLANK_FRAME_STD:
                blank += 1
            if server is not None:
                server.publish(frame)
            elif args.view == "window":
                cv2.imshow("bottom camera", frame)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except KeyboardInterrupt:
        print()
    finally:
        cap.release()
        if server is not None:
            server.stop()
        if args.view == "window":
            with contextlib.suppress(Exception):
                cv2.destroyAllWindows()

    fps = (len(stamps) - 1) / (stamps[-1] - stamps[0]) if len(stamps) > 1 else 0.0
    print(
        f"[bottom] {frames} frames at {fps:.1f} fps "
        f"({failures} dropped reads, {blank} blank, {frozen} frozen)"
    )

    if last_frame is not None and args.save_dir:
        out_dir = Path(args.save_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "bottom.jpg"
        cv2.imwrite(str(path), last_frame)
        print(f"[bottom] saved {path} - open it to confirm the camera sees the floor")

    print()
    if frames == 0:
        print("[bottom] FAIL  the device opened but delivered no frames")
        return 1
    if blank >= frames:
        print("[bottom] FAIL  every frame is blank (black/flat) - no image data")
        return 1
    if frames > 10 and frozen > 0.9 * frames:
        print(f"[bottom] FAIL  feed is frozen ({frozen}/{frames} identical frames)")
        return 1
    if blank:
        print(f"[bottom] WARN  {blank}/{frames} frames were black - intermittent read failures")
    if fps < 0.5 * args.fps:
        print(f"[bottom] WARN  only {fps:.1f} fps (asked for {args.fps}); USB bandwidth or power")
    print(f"[bottom] PASS  the bottom camera is connected and streaming on {device}")
    return 0


DEFAULT_RULES_FILE = "/etc/udev/rules.d/99-sourccey-cameras.rules"


def udev_rule_for(usb_port: str, symlink_name: str) -> str:
    """The rule that gives this physical USB port a stable name.

    Keyed on the PORT, not on the device's serial or vendor id, because all five
    cameras are the same model - only where they are plugged in tells them apart.
    """
    return f'SUBSYSTEM=="video4linux", KERNELS=="{usb_port}", ATTR{{index}}=="0", SYMLINK+="{symlink_name}"'


def find_existing_rules_file() -> str | None:
    """Locate the rules file that already names the other four cameras."""
    for path in sorted(glob.glob("/etc/udev/rules.d/*.rules")):
        try:
            with open(path) as handle:
                text = handle.read()
        except OSError:
            continue
        if any(os.path.basename(link) in text for link in KNOWN_CAMERA_LINKS):
            return path
    return None


def _run(command: list[str], *, input_text: str | None = None) -> tuple[int, str]:
    """Run a command, returning (exit code, combined output)."""
    try:
        completed = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return 127, str(exc)
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def _sudo(command: list[str]) -> list[str]:
    """Prefix with sudo unless we are already root."""
    geteuid = getattr(os, "geteuid", None)
    return command if geteuid is not None and geteuid() == 0 else ["sudo", *command]


def snapshot_camera_names(extra: tuple[str, ...] = ()) -> dict[str, tuple[str | None, str | None]]:
    """Map every configured camera name to the (node, USB port) it resolves to.

    The USB PORT is the identity that matters: /dev/videoN numbers are allowed to
    shuffle when udev re-triggers, but a NAME that starts pointing at a different
    physical port means the rules have been corrupted.
    """
    devices = {d.node: d for d in enumerate_devices()}
    snapshot: dict[str, tuple[str | None, str | None]] = {}
    for link in (*KNOWN_CAMERA_LINKS, *extra):
        if not os.path.exists(link):
            snapshot[link] = (None, None)
            continue
        node = os.path.realpath(link)
        device = devices.get(node)
        snapshot[link] = (node, device.usb_port if device else None)
    return snapshot


def report_naming_changes(
    before: dict[str, tuple[str | None, str | None]],
    after: dict[str, tuple[str | None, str | None]],
) -> bool:
    """Compare two name snapshots and complain about anything that moved."""
    ok = True
    for link in before:
        old_node, old_port = before[link]
        new_node, new_port = after.get(link, (None, None))
        name = os.path.basename(link)

        if old_node is not None and new_node is None:
            print(
                f"[verify] FAIL  {name} EXISTED BEFORE and is gone now - the rules change "
                "broke an existing camera name"
            )
            ok = False
        elif old_node is None and new_node is None:
            print(f"[verify] ----  {name} absent before and after (not wired on this robot)")
        elif old_port and new_port and old_port != new_port:
            print(
                f"[verify] FAIL  {name} now points at USB port {new_port}, was {old_port} - "
                "two rules are fighting over the same name"
            )
            ok = False
        elif old_node != new_node:
            # Legitimate: the kernel can hand out a different node number after a
            # re-trigger. The name still tracks the same physical port.
            print(
                f"[verify] OK    {name} -> {new_node} (was {old_node}; same USB port "
                f"{new_port}, so the name still follows the right camera)"
            )
        else:
            print(f"[verify] OK    {name} -> {new_node} unchanged (port {new_port})")
    return ok


def verify_rules_file_untouched(path: str, before_text: str, added: str) -> bool:
    """Confirm the append added our lines and changed nothing else."""
    try:
        with open(path) as handle:
            after_text = handle.read()
    except OSError as exc:
        print(f"[verify] FAIL  cannot re-read {path}: {exc}")
        return False

    if not after_text.startswith(before_text):
        print(
            f"[verify] FAIL  the existing contents of {path} changed - this should have been an append only"
        )
        print(f"[verify]       restore it from {path}.bak and investigate before rebooting")
        return False
    delta = after_text[len(before_text) :]
    if delta != added:
        print(f"[verify] FAIL  {path} gained unexpected content:")
        print(f"[verify]       expected: {added!r}")
        print(f"[verify]       found:    {delta!r}")
        return False

    print(f"[verify] OK    {path}: every pre-existing line is byte-for-byte unchanged")
    print(f"[verify] OK    only the {len(added.strip().splitlines())} expected line(s) were added")
    return True


def verify_persistence(symlink: str, node: str, rules_file: str) -> bool:
    """Confirm the new name survives a reboot, rather than being a live-only link.

    Three independent signals, because "it works right now" is exactly what a
    temporary hand-made symlink also looks like:
      1. the rule lives in a persistent rules directory, not a tmpfs one;
      2. udev's own database lists the symlink for this device (so udev created
         it from a rule - a manual `ln -s` would not appear);
      3. replaying the device event reproduces the symlink, which is what will
         happen on the next boot.
    """
    print("[verify] ---- will this name survive a reboot? ----")
    ok = True

    real_rules = os.path.realpath(rules_file)
    if real_rules.startswith(("/run/", "/tmp/", "/var/run/")):  # nosec B108 - reject volatile paths
        print(
            f"[verify] FAIL  {real_rules} is on a volatile filesystem - the rule will be GONE "
            "after a power cycle"
        )
        print("[verify]       re-run with --rules-file /etc/udev/rules.d/99-sourccey-cameras.rules")
        ok = False
    elif not real_rules.startswith("/etc/udev/rules.d/"):
        print(f"[verify] WARN  {real_rules} is outside /etc/udev/rules.d - udev may not read it")
        print("[verify]       (persistent rules normally live there; /lib and /usr/lib are for packages)")
    else:
        print(f"[verify] OK    the rule is in {real_rules}, which persists across reboots")

    if not real_rules.endswith(".rules"):
        print(f"[verify] FAIL  udev only reads files ending in .rules - {real_rules} will be ignored on boot")
        ok = False

    # 2. Ask udev's database what symlinks it owns for this device.
    code, output = _run(["udevadm", "info", "--query=symlink", f"--name={node}"])
    if code != 0:
        print(f"[verify] WARN  could not query udev for {node}: {output}")
    else:
        links = output.split()
        if any(link == symlink or link.endswith(f"/{symlink}") for link in links):
            print(
                f"[verify] OK    udev's database lists '{symlink}' for {node}, so udev created "
                "it from a rule (not a manual symlink)"
            )
        else:
            print(
                f"[verify] FAIL  udev does not list '{symlink}' among {node}'s symlinks: {links or '(none)'}"
            )
            print("[verify]       the /dev entry may be a leftover that will NOT come back on boot")
            ok = False

    # 3. Replay the event the way boot will.
    syspath = os.path.join(V4L_SYSFS, os.path.basename(node))
    code, output = _run(_sudo(["udevadm", "test", syspath]))
    if code != 0:
        print(f"[verify] WARN  `udevadm test {syspath}` did not run cleanly; skipping the replay check")
    elif symlink in output:
        print(f"[verify] OK    replaying the device event recreates '{symlink}' - the next boot will too")
    else:
        print(f"[verify] FAIL  replaying the device event did NOT produce '{symlink}'")
        print("[verify]       the rule is not matching; the name will disappear on reboot")
        ok = False

    return ok


def verify_naming(args: argparse.Namespace) -> bool:
    """Standalone audit: are all the camera names present, correct, and permanent?"""
    print("[verify] ---- camera naming audit ----")
    names = (*KNOWN_CAMERA_LINKS, f"/dev/{args.symlink_name}")
    snapshot = snapshot_camera_names((f"/dev/{args.symlink_name}",))

    ok = True
    seen_ports: dict[str, str] = {}
    for link in names:
        node, port = snapshot.get(link, (None, None))
        name = os.path.basename(link)
        if node is None:
            level = "WARN" if link.endswith(args.symlink_name) else "FAIL"
            print(f"[verify] {level}  {name} does not exist")
            ok = ok and level == "WARN"
            continue
        # Two names on one port means a duplicated rule, which is how "it worked
        # yesterday" turns into a camera swap after a reboot.
        if port and port in seen_ports:
            print(f"[verify] FAIL  {name} and {seen_ports[port]} both point at USB port {port}")
            ok = False
        elif port:
            seen_ports[port] = name
        print(f"[verify] OK    {name} -> {node} (port {port or 'unknown'})")

    rules_file = args.rules_file or find_existing_rules_file()
    if rules_file is None:
        print(
            "[verify] WARN  no udev rules file naming these cameras was found; the names may "
            "come from somewhere else entirely"
        )
        return ok

    target = f"/dev/{args.symlink_name}"
    if os.path.exists(target):
        ok = verify_persistence(args.symlink_name, os.path.realpath(target), rules_file) and ok
    return ok


def install_udev_rule(device: VideoDevice, args: argparse.Namespace) -> bool:
    """Give the identified camera a stable /dev/<name>, like the other four."""
    print()
    print("[udev] ---- naming this camera ----")
    if not device.usb_port:
        print("[udev] FAIL  this device has no USB port path, so it cannot be named by port")
        return False

    symlink = args.symlink_name
    rule = udev_rule_for(device.usb_port, symlink)
    rules_file = args.rules_file or find_existing_rules_file() or DEFAULT_RULES_FILE

    existing_text = ""
    if os.path.exists(rules_file):
        try:
            with open(rules_file) as handle:
                existing_text = handle.read()
        except OSError as exc:
            print(f"[udev] FAIL  cannot read {rules_file}: {exc}")
            return False

    if existing_text:
        camera_rules = [
            line for line in existing_text.splitlines() if "video4linux" in line and "SYMLINK" in line
        ]
        if camera_rules:
            print(f"[udev] existing camera rules in {rules_file}:")
            for line in camera_rules:
                print(f"[udev]   {line.strip()}")

    if f'SYMLINK+="{symlink}"' in existing_text:
        if rule in existing_text.replace("  ", " "):
            print(f"[udev] a rule for {symlink} on port {device.usb_port} is already present")
            return verify_symlink(symlink, device, args)
        print(f"[udev] FAIL  {rules_file} already has a rule for {symlink}, but for a different port")
        print(
            "[udev]       edit or remove that line by hand, then re-run - this script will "
            "not rewrite existing rules"
        )
        return False

    print()
    print(f"[udev] will append to {rules_file}:")
    print(f"[udev]   {rule}")
    print("[udev] then reload udev and confirm the name appears.")
    if input("[udev] Type 'yes' to write it: ").strip().lower() != "yes":
        print("[udev] skipped - nothing was written")
        return True

    # Record where every existing camera name points BEFORE touching anything, so
    # the after-state can be compared against it rather than merely eyeballed.
    names_before = snapshot_camera_names((f"/dev/{symlink}",))
    print("[udev] recorded the current camera names for comparison afterwards")

    # Back up before touching a system file, even for an append.
    if os.path.exists(rules_file):
        backup = f"{rules_file}.bak"
        code, output = _run(_sudo(["cp", "-n", rules_file, backup]))
        if code == 0:
            print(f"[udev] backed up {rules_file} -> {backup}")
        else:
            print(f"[udev] WARN  could not back up {rules_file}: {output}")

    # `tee -a` rather than a Python write, so sudo can own the privileged part.
    header = "" if existing_text.endswith("\n") or not existing_text else "\n"
    addition = f"{header}# Sourccey bottom camera (added by sourccey-check-bottom-camera)\n{rule}\n"
    code, output = _run(_sudo(["tee", "-a", rules_file]), input_text=addition)
    if code != 0:
        print(f"[udev] FAIL  could not write {rules_file}: {output}")
        print(f"[udev]       add it by hand: echo {shlex.quote(rule)} | sudo tee -a {rules_file}")
        return False
    print(f"[udev] wrote the rule to {rules_file}")

    for command in (
        ["udevadm", "control", "--reload-rules"],
        ["udevadm", "trigger", "--subsystem-match=video4linux"],
    ):
        code, output = _run(_sudo(command))
        if code != 0:
            print(f"[udev] FAIL  `{' '.join(command)}` failed: {output}")
            return False
    print("[udev] reloaded udev rules")

    if not verify_symlink(symlink, device, args):
        return False

    # Everything below answers "did anything ELSE change, and will this survive a
    # power cycle" - the two questions a working /dev entry cannot answer by itself.
    print()
    print("[verify] ---- checking nothing else moved ----")
    ok = verify_rules_file_untouched(rules_file, existing_text, addition)
    ok = report_naming_changes(names_before, snapshot_camera_names((f"/dev/{symlink}",))) and ok
    print()
    ok = verify_persistence(symlink, os.path.realpath(f"/dev/{symlink}"), rules_file) and ok

    print()
    if ok:
        print("[verify] PASS  all camera names are intact and permanent")
        print("[verify]       (re-run with --verify-names any time, including after a reboot)")
    else:
        print("[verify] FAIL  something is not right - see the lines above")
        print(f"[verify]       the previous rules file is saved as {rules_file}.bak")
        print("[verify]       resolve this BEFORE rebooting the robot")
    return ok


def verify_symlink(symlink: str, device: VideoDevice, args: argparse.Namespace) -> bool:
    """Confirm /dev/<name> now exists and points at the right camera."""
    path = f"/dev/{symlink}"
    deadline = time.monotonic() + args.settle_seconds
    while time.monotonic() < deadline:
        if os.path.exists(path):
            target = os.path.realpath(path)
            match = next((d for d in enumerate_devices() if d.node == target), None)
            if match is not None and match.usb_port == device.usb_port:
                print(f"[udev] PASS  {path} -> {target} (port {match.usb_port})")
                print(f'[udev]       use index_or_path="{path}" in sourccey_cameras_config()')
                return True
            print(
                f"[udev] FAIL  {path} exists but points at {target}, which is not the "
                f"camera on port {device.usb_port}"
            )
            return False
        time.sleep(0.3)

    print(f"[udev] FAIL  {path} did not appear within {args.settle_seconds:.0f}s")
    print("[udev]       the rule is written; try re-plugging the camera, or reboot the Pi")
    print(f"[udev]       and check with: udevadm info --name={device.node} | head -20")
    return False


def print_wiring_hints(device: VideoDevice | None, node: str) -> None:
    """Tell the operator exactly what to put in the config when they wire it up."""
    print()
    print("[bottom] ---- to wire it into the host later ----")
    if device is None or device.stable_path == device.node:
        print(f'[bottom] index_or_path="{node}"')
        print("[bottom] NOTE  /dev/videoN numbering moves when devices are re-plugged or")
        print("[bottom]       re-enumerated at boot. Prefer a by-path name if one appears")
        print("[bottom]       under /dev/v4l/by-path/ for this camera.")
        return

    print(f'[bottom] index_or_path="{device.stable_path}"')
    print("[bottom]       (stable across re-plug, unlike the /dev/videoN number)")
    if device.usb_port:
        rules_file = find_existing_rules_file() or DEFAULT_RULES_FILE
        print()
        print("[bottom] or give it a name like the other four - re-run with --name-it to have")
        print(f"[bottom] this rule written to {rules_file} for you:")
        print(f"[bottom]   {udev_rule_for(device.usb_port, 'cameraFrontBottom')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find and check the underside camera on the Pi (bypasses sourccey-host)."
    )
    parser.add_argument(
        "--identify",
        action="store_true",
        help="Unplug test: see which USB camera disappears, then check it.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="V4L2 device to check (e.g. /dev/video8). Omit to auto-detect.",
    )
    parser.add_argument("--list", action="store_true", help="Only list USB cameras, then exit.")
    parser.add_argument(
        "--name-it",
        action="store_true",
        help="Install a udev rule so this camera gets a stable /dev name (asks first, needs sudo).",
    )
    parser.add_argument(
        "--verify-names",
        action="store_true",
        help="Audit all camera names (present, unique, permanent) and exit. Safe to re-run "
        "after a reboot; changes nothing.",
    )
    parser.add_argument(
        "--symlink-name",
        default="cameraFrontBottom",
        help="Name to give it under /dev (default: cameraFrontBottom, matching the other four).",
    )
    parser.add_argument(
        "--rules-file",
        default=None,
        help="udev rules file to append to; default is whichever file already names the cameras.",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=15.0,
        help="How long to wait for udev after an unplug/re-plug during --identify.",
    )
    parser.add_argument("--width", type=int, default=320, help="Requested frame width.")
    parser.add_argument("--height", type=int, default=240, help="Requested frame height.")
    parser.add_argument("--fps", type=int, default=30, help="Requested frame rate.")
    parser.add_argument(
        "--fourcc",
        default="MJPG",
        help="Pixel format; MJPG is what this camera needs for 30 FPS. Pass '' to let it pick.",
    )
    parser.add_argument("--seconds", type=float, default=5.0, help="How long to sample.")
    parser.add_argument(
        "--view",
        choices=("none", "mjpeg", "window"),
        default="none",
        help="none = probe and save a frame; mjpeg = watch from your PC in a browser.",
    )
    parser.add_argument("--http-port", type=int, default=8093, help="Port for the MJPEG view.")
    parser.add_argument("--save-dir", default="camera_health", help="Where to write the captured frame.")
    args = parser.parse_args()

    if not os.path.isdir(V4L_SYSFS):
        print(f"[bottom] FAIL  {V4L_SYSFS} does not exist - run this ON THE PI")
        return 1

    if args.view == "window" and not gui_available():
        print("[bottom] FAIL  --view window was requested but this OpenCV build has no GUI support")
        print("[bottom]       (the package uses opencv-python-headless, so cv2.imshow cannot draw)")
        print("[bottom]       use --view mjpeg to watch it in a browser instead")
        return 1

    if args.list:
        print_inventory()
        return 0

    if args.verify_names:
        return 0 if verify_naming(args) else 1

    print("[bottom] ---- bottom camera check ----")
    device_info: VideoDevice | None = None

    if args.device:
        if not os.path.exists(args.device):
            print(f"[bottom] FAIL  no such device: {args.device}")
            print("[bottom]       run with --list to see the USB cameras on this Pi")
            return 1
        node = args.device
        real = os.path.realpath(node)
        device_info = next((d for d in enumerate_devices() if d.node == real), None)
    elif args.identify:
        device_info = identify_by_unplug(args)
        if device_info is None:
            return 1
        node = device_info.node
    else:
        unclaimed = print_inventory()
        if not unclaimed:
            print()
            print("[bottom] FAIL  every USB camera is already claimed by the robot config")
            print("[bottom]       the bottom camera is not enumerating: check its cable and hub,")
            print("[bottom]       then `lsusb` and `dmesg -T | tail -30`")
            return 1
        if len(unclaimed) > 1:
            print()
            print(f"[bottom] FAIL  {len(unclaimed)} unclaimed USB cameras - cannot tell which is")
            print("[bottom]       the bottom one. Re-run with --identify to unplug-test it.")
            return 1
        device_info = unclaimed[0]
        node = device_info.node
        print()
        print(f"[bottom] exactly one unclaimed USB camera: {node} - treating it as the bottom camera")

    print(f"[bottom] checking {node}")
    result = stream_check(node, args)
    if result != 0:
        return result

    if args.name_it:
        if device_info is None:
            print()
            print("[udev] FAIL  cannot name this device: it is not a USB camera node")
            return 1
        # A camera that failed its stream check is not one to bless with a name,
        # which is why this runs only after the check passed.
        return 0 if install_udev_rule(device_info, args) else 1

    print_wiring_hints(device_info, node)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
