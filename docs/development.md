# Development and distribution

## Validate the package

Install the development dependencies, run the tests, and build the package:

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m build
python -m pip install twine
python -m twine check dist/*
```

## Local and offline installation

The package does not need to be online or published. An editable local install
is sufficient:

```bash
uv pip install -e PATH_TO_LEROBOT_ROBOT_SOURCCEY
```

For another computer, choose one of these options:

- Copy the package directory to that computer and install it from the path.
- Put it in a Git repository and install it from a Git URL.
- Publish it to PyPI and install it with
  `python -m pip install lerobot_robot_sourccey`.

Publishing is a distribution convenience, not a LeRobot requirement.

## Optional dependency groups

| Extra | Purpose |
| --- | --- |
| `hardware` | Linux GPIO, I2C, IMU, and battery dependencies |
| `record` | LeRobot dataset and recording dependencies |
| `dev` | Tests, builds, and Protobuf development tools |

Return to the [documentation index](README.md).
