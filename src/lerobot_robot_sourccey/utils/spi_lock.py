from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

try:
    import fcntl  # Linux only
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore


@contextmanager
def spi_device_lock(
    *,
    lock_path: str = "/tmp/sourccey_mcp3008.lock",
    timeout_s: float = 0.25,
    poll_s: float = 0.005,
) -> Iterator[None]:
    """
    Cross-process lock for shared SPI devices (e.g. MCP3008) on Linux.

    Why:
    - The robot process (Z actuator loop) and the desktop app (battery.py spawned by Tauri)
      can otherwise access the MCP3008 concurrently, causing intermittent bad reads/failures.

    Behavior:
    - On Linux: uses an advisory flock() on `lock_path`.
    - On non-Linux (e.g. Windows dev): no-op.
    """
    if fcntl is None:
        yield
        return

    start = time.monotonic()
    with open(lock_path, "w") as f:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - start > float(timeout_s):
                    raise TimeoutError(f"Timed out waiting for SPI lock: {lock_path}")
                time.sleep(float(poll_s))

        try:
            yield
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass


