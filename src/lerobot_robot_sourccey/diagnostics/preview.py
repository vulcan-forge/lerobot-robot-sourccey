"""Shared browser preview and GUI detection for hardware diagnostics."""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np


class MjpegServer:
    """Optional browser view, for running this check from a headless machine."""

    def __init__(self, port: int, title: str) -> None:
        self.port = int(port)
        self._title = title
        self._stop_event = threading.Event()
        self._jpeg: bytes | None = None
        self._lock = threading.Lock()
        # The diagnostic viewer is intentionally reachable from the operator's desktop.
        self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), self._handler())  # nosec B104
        self.port = self._httpd.server_port
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # keep the console readable
                pass

            def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
                if self.path in ("/", "/index.html"):
                    page = (
                        f"<html><head><title>{server._title}</title></head>"
                        "<body style='margin:0;background:#111;color:#ddd;"
                        "font-family:sans-serif;text-align:center'>"
                        f"<h3>{server._title}</h3>"
                        "<img src='/stream.mjpg' style='max-width:100%'></body></html>"
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    self.wfile.write(page)
                    return
                if self.path != "/stream.mjpg":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Age", "0")
                self.send_header("Cache-Control", "no-cache, private")
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
                self.end_headers()
                try:
                    while not server._stop_event.is_set():
                        with server._lock:
                            jpeg = server._jpeg
                        if jpeg is None:
                            server._stop_event.wait(0.05)
                            continue
                        self.wfile.write(b"--FRAME\r\n")
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Content-Length", str(len(jpeg)))
                        self.end_headers()
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                        server._stop_event.wait(0.05)
                except (BrokenPipeError, ConnectionResetError):
                    return

        return Handler

    def publish(self, frame: np.ndarray) -> None:
        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            with self._lock:
                self._jpeg = buffer.tobytes()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._httpd.shutdown()
            self._thread.join(timeout=2.0)
        self._httpd.server_close()


def lan_ip() -> str:
    """Best guess at this machine's LAN address, for printing the viewing URL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "<pi-ip>"
    finally:
        sock.close()


_gui_available: bool | None = None


def gui_available() -> bool:
    """True only if this OpenCV build can actually open a window.

    This package uses `opencv-python-headless` (see pyproject.toml), which ships
    without highgui: `imshow` raises instead of drawing. Having a desktop is
    therefore NOT enough - the check has to be about the build, and probing with
    a real window is the only reliable way to ask, since the build flags are not
    always reported consistently.
    """
    global _gui_available
    if _gui_available is None:
        try:
            cv2.namedWindow("__sourccey_gui_probe__", cv2.WINDOW_AUTOSIZE)
            cv2.destroyWindow("__sourccey_gui_probe__")
            _gui_available = True
        except Exception:  # noqa: BLE001 - any failure means no usable GUI
            _gui_available = False
    return _gui_available
