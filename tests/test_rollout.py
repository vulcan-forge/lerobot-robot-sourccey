import threading
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

upstream = pytest.importorskip("lerobot.rollout")
if not hasattr(upstream, "InteractiveSession"):
    pytest.skip("Desktop rollout requires the LeRobot 0.6.2 API", allow_module_level=True)

from lerobot_robot_sourccey import rollout as module  # noqa: E402


def test_config_extends_upstream_without_changing_it():
    assert "shutdown_event_path" not in {field.name for field in fields(upstream.RolloutConfig)}
    assert "shutdown_event_path" in {field.name for field in fields(module.SourcceyRolloutConfig)}


def test_real_stop_file_sets_shared_event_and_watcher_is_joined(tmp_path):
    path = tmp_path / "stop"
    shutdown = threading.Event()
    with module.watch_shutdown_file(str(path), shutdown):
        path.touch()
        assert shutdown.wait(2)
    assert not any(thread.name == "sourccey-rollout-stop" for thread in threading.enumerate())


@pytest.mark.parametrize("failure_stage", [None, "build", "setup", "run", "teardown"])
def test_all_exit_paths_stop_watcher_and_release_visualization(monkeypatch, tmp_path, failure_stage):
    path = tmp_path / "stop"
    cfg = SimpleNamespace(
        shutdown_event_path=str(path),
        inference=SimpleNamespace(log_level="INFO"),
        display_data=True,
        display_mode="rerun",
        display_ip=None,
        display_port=None,
        interactive=False,
        strategy=object(),
    )
    engine = SimpleNamespace(failed=False)
    context = SimpleNamespace(policy=SimpleNamespace(inference=engine))
    strategy = Mock()
    build = Mock(return_value=context)
    if failure_stage == "build":
        build.side_effect = RuntimeError("build")
    elif failure_stage:
        getattr(strategy, failure_stage).side_effect = RuntimeError(failure_stage)
    monkeypatch.setattr(module, "build_rollout_context", build)
    monkeypatch.setattr(module, "create_strategy", lambda _: strategy)
    monkeypatch.setattr(
        module, "ProcessSignalHandler", lambda **_: SimpleNamespace(shutdown_event=threading.Event())
    )
    monkeypatch.setattr(module, "init_visualization", Mock())
    close = Mock()
    monkeypatch.setattr(module, "shutdown_visualization", close)
    if failure_stage:
        with pytest.raises(RuntimeError, match=failure_stage):
            module.run_rollout(cfg)
    else:
        module.run_rollout(cfg)
    assert strategy.teardown.call_count == int(failure_stage != "build")
    close.assert_called_once_with("rerun")
    assert not any(thread.name == "sourccey-rollout-stop" for thread in threading.enumerate())


def test_stop_request_reaches_upstream_loop_and_teardown(monkeypatch, tmp_path):
    path = tmp_path / "stop"
    cfg = SimpleNamespace(
        shutdown_event_path=str(path),
        inference=SimpleNamespace(log_level="INFO"),
        display_data=False,
        interactive=False,
        strategy=object(),
    )
    event = threading.Event()
    monkeypatch.setattr(module, "ProcessSignalHandler", lambda **_: SimpleNamespace(shutdown_event=event))
    context = SimpleNamespace(policy=SimpleNamespace(inference=SimpleNamespace(failed=False)))

    def build(config, shutdown):
        assert shutdown is event
        return context

    monkeypatch.setattr(module, "build_rollout_context", build)
    strategy = Mock()

    def run(ctx):
        path.touch()
        assert event.wait(2)

    strategy.run.side_effect = run
    monkeypatch.setattr(module, "create_strategy", lambda _: strategy)
    module.run_rollout(cfg)
    strategy.teardown.assert_called_once_with(context)
