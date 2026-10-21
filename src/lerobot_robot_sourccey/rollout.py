"""Desktop lifecycle adapter using LeRobot's public rollout context and strategies.

Requires the LeRobot 0.6.2 rollout API; install this package's ``rollout`` extra.
Hardware, inference, recording and strategy teardown stay owned by LeRobot.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import lerobot.scripts.lerobot_rollout  # noqa: F401 -- register built-in hardware configurations
from lerobot.configs import parser
from lerobot.rollout import (
    InteractiveSession,
    LinkedEvent,
    RolloutConfig,
    build_rollout_context,
    create_strategy,
)
from lerobot.utils import init_logging, register_third_party_plugins
from lerobot.utils.process import ProcessSignalHandler
from lerobot.utils.visualization_utils import init_visualization, shutdown_visualization

logger = logging.getLogger(__name__)


@dataclass
class SourcceyRolloutConfig(RolloutConfig):
    shutdown_event_path: str | None = None


@contextmanager
def watch_shutdown_file(path: str | None, shutdown: threading.Event) -> Iterator[None]:
    """Translate a desktop stop request, joining the watcher on every exit path."""
    stopped = threading.Event()

    def watch() -> None:
        while not stopped.is_set() and not shutdown.is_set():
            if path is not None and Path(path).is_file():
                logger.info("Desktop stop requested; finalizing rollout")
                shutdown.set()
                return
            stopped.wait(0.1)

    worker = threading.Thread(target=watch, name="sourccey-rollout-stop", daemon=True) if path else None
    if worker is not None:
        worker.start()
    try:
        yield
    finally:
        stopped.set()
        if worker is not None:
            worker.join()


def run_rollout(cfg: SourcceyRolloutConfig) -> None:
    """Run upstream strategies, finalizing data and stopping listeners on failure too."""
    init_logging(console_level=cfg.inference.log_level)
    shutdown = ProcessSignalHandler(use_threads=True, display_pid=False).shutdown_event
    if not isinstance(shutdown, threading.Event):
        raise RuntimeError("Threaded rollout requires a threading.Event")
    with watch_shutdown_file(cfg.shutdown_event_path, shutdown):
        try:
            if cfg.display_data:
                init_visualization(
                    cfg.display_mode, session_name="rollout", ip=cfg.display_ip, port=cfg.display_port
                )
            event = LinkedEvent(shutdown) if cfg.interactive else shutdown
            strategy = create_strategy(cfg.strategy)
            ctx = build_rollout_context(cfg, event)
            session: InteractiveSession | None = None
            try:
                strategy.setup(ctx)
                if cfg.interactive:
                    session = InteractiveSession(strategy, ctx)
                    session.run()
                else:
                    strategy.run(ctx)
            except KeyboardInterrupt:
                logger.info("Interrupted by user")
            finally:
                strategy.teardown(ctx)
            failure = session.controller if session is not None else ctx.policy.inference
            if failure.failed:
                logger.error("Rollout fault: %s", failure.failure_traceback)
                raise SystemExit(1)
        finally:
            if cfg.display_data:
                shutdown_visualization(cfg.display_mode)


@parser.wrap()
def rollout(cfg: SourcceyRolloutConfig) -> None:
    run_rollout(cfg)


def main() -> None:
    register_third_party_plugins()
    cast(Callable[[], None], rollout)()


if __name__ == "__main__":
    main()
