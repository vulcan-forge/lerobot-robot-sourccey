# Development and distribution

## Validate the package

Install the development dependencies, run the tests, and build the same clean
artifacts that remote users will receive:

```bash
python -m pip install -e ".[dev]"
python -m pytest
uv build --no-sources
python -m pip install twine
python -m twine check dist/*
```

`--no-sources` ensures the build does not accidentally depend on local uv
source overrides. The CI workflow also installs both the wheel and source
distribution in isolated environments and checks plugin registration and
packaged hardware assets.

## Local and offline installation

The package does not need to be online or published. An editable local install
is sufficient:

```bash
uv pip install -e PATH_TO_LEROBOT_ROBOT_SOURCCEY
```

For another computer, choose one of these options:

- Copy the package directory to that computer and install it from the path.
- Install the public repository directly:
  `uv pip install "git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@main"`.
- Publish it to PyPI and install it with
  `uv add lerobot-robot-sourccey`.

Publishing is a distribution convenience, not a LeRobot requirement.

## Publish a tagged release to PyPI

Releases use `.github/workflows/release.yml` and PyPI Trusted Publishing, so no
long-lived PyPI token is stored in GitHub.

Before the first release, configure a pending Trusted Publisher in your PyPI
account with these exact values:

| PyPI field | Value |
| --- | --- |
| PyPI project name | `lerobot-robot-sourccey` |
| GitHub owner | `vulcan-forge` |
| Repository | `lerobot-robot-sourccey` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Also create a protected GitHub environment named `pypi`. Then update the
version in `pyproject.toml`, commit and push the release, and create a matching
tag:

```bash
uv version --bump patch --frozen
git add pyproject.toml
git commit -m "Release v0.2.1"
git tag -a v0.2.1 -m "v0.2.1"
git push origin main
git push origin v0.2.1
```

Every PyPI version is immutable. If a publish needs a code change, increment
the version and create a new tag rather than reusing the old one.

## Optional dependency groups

| Extra | Purpose |
| --- | --- |
| `hardware` | Linux GPIO, I2C, IMU, and battery dependencies |
| `record` | LeRobot dataset and recording dependencies |
| `dev` | Tests, builds, and Protobuf development tools |

Return to the [documentation index](README.md).
