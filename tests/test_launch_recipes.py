"""The development and debug launch recipes, driven through the real justfile.

The recipes are executed for real; only ``uv`` is replaced by a recorder, so no
LiveKit worker is started and no credential is needed. One test then replays the
recorded argument vector against the real LiveKit CLI, which gets as far as
asking for a LiveKit URL it is deliberately not given.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_local_merge_gate import REPOSITORY_ROOT, run, write_executable

EXPECTED_LAUNCH_TARGET = "language_tutor/agent.py"
LIVEKIT_CREDENTIAL_VARS = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")


@pytest.fixture
def launch_project(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(REPOSITORY_ROOT / "justfile", project / "justfile")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launch_log = tmp_path / "launch.log"
    write_executable(
        bin_dir / "uv",
        f"""#!/bin/sh
printf 'LOG_LEVEL=%s ARGS=%s\\n' "$LOG_LEVEL" "$*" >> {launch_log}
""",
    )
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return project, launch_log, env


def recorded_launch_arguments(launch_log: Path) -> list[str]:
    recorded = launch_log.read_text().strip()
    _, _, arguments = recorded.partition("ARGS=run -- ")
    assert arguments, f"recipe did not run the project interpreter: {recorded}"
    return arguments.split()


@pytest.mark.parametrize(
    ("recipe", "log_level"), [("start", "INFO"), ("debug", "DEBUG")]
)
def test_launch_recipe_runs_the_migrated_livekit_agents_cli(
    launch_project: tuple[Path, Path, dict[str, str]],
    recipe: str,
    log_level: str,
):
    project, launch_log, env = launch_project

    run("just", recipe, cwd=project, env=env)

    recorded = launch_log.read_text().strip()
    assert recorded == (
        f"LOG_LEVEL={log_level.lower()} ARGS=run -- python -m livekit.agents start "
        f"{EXPECTED_LAUNCH_TARGET} --dev --log-level {log_level}"
    )


def test_launch_recipes_do_not_use_the_deprecated_rich_python_cli(
    launch_project: tuple[Path, Path, dict[str, str]],
):
    """`python -m <agent module> dev` was the deprecated 0.x entry point."""
    project, launch_log, env = launch_project

    run("just", "start", cwd=project, env=env)

    recorded = launch_log.read_text()
    assert "python -m livekit.agents start" in recorded
    assert "python -m language_tutor.agent" not in recorded


def test_launch_target_exists_in_the_repository():
    assert (REPOSITORY_ROOT / EXPECTED_LAUNCH_TARGET).is_file()


@pytest.mark.parametrize("recipe", ["start", "debug"])
def test_recorded_launch_arguments_reach_the_real_agent_server(
    launch_project: tuple[Path, Path, dict[str, str]],
    recipe: str,
):
    """Replay the recipe's own argv against the real CLI, minus LiveKit creds.

    Startup gets through argument parsing, logging setup and AgentServer
    discovery, and stops exactly where it would need a LiveKit server — so the
    launch path is proven without one.
    """
    project, launch_log, env = launch_project
    run("just", recipe, cwd=project, env=env)
    arguments = recorded_launch_arguments(launch_log)
    assert arguments[0] == "python"

    child_env = {
        key: value
        for key, value in os.environ.items()
        if key not in LIVEKIT_CREDENTIAL_VARS
    } | {"PYTHONPATH": str(REPOSITORY_ROOT)}
    result = subprocess.run(
        [sys.executable, *arguments[1:]],
        cwd=REPOSITORY_ROOT,
        env=child_env,
        check=False,
        text=True,
        capture_output=True,
        timeout=300,
    )

    output = result.stdout + result.stderr
    assert "ws_url is required" in output, output
    assert "Unknown level" not in output, output
    assert "Traceback" not in output.split("worker failed")[0], output
