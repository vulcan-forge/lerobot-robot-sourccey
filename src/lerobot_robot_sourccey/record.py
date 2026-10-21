# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
# Copyright 2026 Vulcan Robotics, Inc. All rights reserved.
# Licensed under the Apache License, Version 2.0.
"""Sourccey episode controls using LeRobot's dataset API and recording loop.

The session owns its keyboard events; no upstream globals or listeners are patched.
The schema, frame processing, hardware loop, and video encoder remain LeRobot's.
"""

import logging
from contextlib import ExitStack

from lerobot.common.control_utils import sanity_check_dataset_robot_compatibility
from lerobot.configs import parser
from lerobot.datasets import (
    LeRobotDataset,
    VideoEncodingManager,
    aggregate_pipeline_dataset_features,
    create_initial_features,
)
from lerobot.robots import Robot, make_robot_from_config
from lerobot.scripts.lerobot_record import RecordConfig, record_loop
from lerobot.teleoperators import Teleoperator, make_teleoperator_from_config
from lerobot.utils.feature_utils import combine_feature_dicts
from lerobot.utils.import_utils import register_third_party_plugins
from lerobot.utils.utils import init_logging, log_say
from lerobot.utils.visualization_utils import init_visualization, shutdown_visualization

from .controls import make_control_processors
from .teleoperate import disconnect_robot


def open_dataset(cfg: RecordConfig, robot: Robot, processors: tuple) -> LeRobotDataset:
    features = combine_feature_dicts(
        *(
            aggregate_pipeline_dataset_features(
                pipeline=pipeline,
                initial_features=create_initial_features(**initial),
                use_videos=cfg.dataset.video,
            )
            for pipeline, initial in (
                (processors[0], {"action": robot.action_features}),
                (processors[2], {"observation": robot.observation_features}),
            )
        )
    )
    camera_count = len(robot.cameras)
    options = dict(
        root=cfg.dataset.root,
        image_writer_processes=cfg.dataset.num_image_writer_processes if camera_count else 0,
        image_writer_threads=cfg.dataset.num_image_writer_threads_per_camera * camera_count,
        batch_encoding_size=cfg.dataset.video_encoding_batch_size,
        rgb_encoder=cfg.dataset.rgb_encoder,
        depth_encoder=cfg.dataset.depth_encoder,
        encoder_threads=cfg.dataset.encoder_threads,
        streaming_encoding=cfg.dataset.streaming_encoding,
        encoder_queue_maxsize=cfg.dataset.encoder_queue_maxsize,
    )
    if cfg.resume:
        dataset = LeRobotDataset.resume(cfg.dataset.repo_id, **options)
        try:
            sanity_check_dataset_robot_compatibility(dataset, robot, cfg.dataset.fps, features)
        except BaseException:
            dataset.finalize()
            raise
        return dataset
    if cfg.dataset.repo_id.split("/", 1)[-1].startswith("eval_"):
        raise ValueError("Dataset names starting with eval_ are reserved for policy evaluation")
    cfg.dataset.stamp_repo_id()
    return LeRobotDataset.create(
        cfg.dataset.repo_id,
        cfg.dataset.fps,
        robot_type=robot.name,
        features=features,
        use_videos=cfg.dataset.video,
        **options,
    )


def run_episodes(
    cfg: RecordConfig,
    robot: Robot,
    teleop: Teleoperator,
    dataset: LeRobotDataset,
    processors: tuple,
    events: dict[str, bool],
) -> None:
    options = dict(
        robot=robot,
        teleop=teleop,
        events=events,
        fps=cfg.dataset.fps,
        teleop_action_processor=processors[0],
        robot_action_processor=processors[1],
        robot_observation_processor=processors[2],
        single_task=cfg.dataset.single_task,
        display_data=cfg.display_data,
        display_mode=cfg.display_mode,
        display_compressed_images=cfg.display_compressed_images
        or (cfg.display_data and cfg.display_ip is not None and cfg.display_port is not None),
    )
    saved = 0
    with VideoEncodingManager(dataset):
        while saved < cfg.dataset.num_episodes and not events["stop_recording"]:
            log_say(f"Recording episode {dataset.num_episodes}", cfg.play_sounds)
            record_loop(dataset=dataset, control_time_s=cfg.dataset.episode_time_s, **options)
            if not events["stop_recording"] and (
                saved < cfg.dataset.num_episodes - 1 or events["rerecord_episode"]
            ):
                log_say("Reset the environment", cfg.play_sounds)
                record_loop(control_time_s=cfg.dataset.reset_time_s, **options)
            if events["rerecord_episode"]:
                events["rerecord_episode"] = False
                events["exit_early"] = False
                dataset.clear_episode_buffer()
                continue
            # An immediate stop before the first frame has no episode to save.
            if dataset.has_pending_frames():
                dataset.save_episode()
                saved += 1


@parser.wrap()
def record(cfg: RecordConfig) -> LeRobotDataset:
    init_logging()
    robot = make_robot_from_config(cfg.robot)
    teleop = make_teleoperator_from_config(cfg.teleop)
    events = {"exit_early": False, "rerecord_episode": False, "stop_recording": False}
    processors = make_control_processors(teleop, robot, events)
    with ExitStack() as resources:
        dataset = open_dataset(cfg, robot, processors)
        resources.callback(dataset.finalize)
        resources.callback(teleop.disconnect)
        teleop.connect()
        resources.callback(disconnect_robot, robot)
        robot.connect()
        if cfg.display_data:
            resources.callback(shutdown_visualization, cfg.display_mode)
            init_visualization(
                cfg.display_mode, session_name="recording", ip=cfg.display_ip, port=cfg.display_port
            )
        try:
            run_episodes(cfg, robot, teleop, dataset, processors, events)
        except KeyboardInterrupt:
            logging.info("Recording interrupted")
    if cfg.dataset.push_to_hub and dataset.num_episodes > 0:
        dataset.push_to_hub(tags=cfg.dataset.tags, private=cfg.dataset.private)
    return dataset


def main() -> None:
    register_third_party_plugins()
    record()


if __name__ == "__main__":
    main()
