import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parents[1]


def run(
    *command: str,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )


def write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def recipe_project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    shutil.copy(REPOSITORY_ROOT / "justfile", tmp_path / "justfile")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_executable(
        bin_dir / "uv",
        """#!/bin/sh
case "$*" in
  *pyright*) [ ! -f .fail-lint ] ;;
  *pytest*) [ ! -f .fail-tests ] ;;
  *) exit 0 ;;
esac
""",
    )
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return tmp_path, env


@pytest.mark.parametrize(
    ("failure_marker", "expected_output"),
    [(".fail-lint", "pyright"), (".fail-tests", "pytest")],
)
def test_check_refuses_each_failing_quality_tier(
    recipe_project: tuple[Path, dict[str, str]],
    failure_marker: str,
    expected_output: str,
):
    project, env = recipe_project
    (project / failure_marker).touch()

    result = run("just", "check", cwd=project, env=env, check=False)

    assert result.returncode != 0
    assert expected_output in result.stdout + result.stderr


def test_check_succeeds_only_when_lint_types_and_tests_pass(
    recipe_project: tuple[Path, dict[str, str]],
):
    project, env = recipe_project

    result = run("just", "check", cwd=project, env=env)

    output = result.stdout + result.stderr
    assert "pyright" in output
    assert "pytest" in output


def test_prepare_installs_hooks_and_push_obeys_pre_push_gate(tmp_path: Path):
    remote = tmp_path / "remote.git"
    checkout = tmp_path / "checkout"
    run("git", "init", "--bare", str(remote), cwd=tmp_path)
    run("git", "init", str(checkout), cwd=tmp_path)
    run("git", "config", "user.name", "Gate Test", cwd=checkout)
    run("git", "config", "user.email", "gate@example.com", cwd=checkout)
    run("git", "remote", "add", "origin", str(remote), cwd=checkout)

    (checkout / "README.md").write_text("gate journey\n")
    run("git", "add", "README.md", cwd=checkout)
    run("git", "commit", "-m", "test fixture", cwd=checkout)

    shutil.copy(REPOSITORY_ROOT / "justfile", checkout / "justfile")
    shutil.copy(REPOSITORY_ROOT / "package.json", checkout / "package.json")
    shutil.copytree(REPOSITORY_ROOT / ".husky", checkout / ".husky")
    run("pnpm", "run", "prepare", cwd=checkout)
    hooks_path = run(
        "git", "config", "--get", "core.hooksPath", cwd=checkout
    ).stdout.strip()
    assert hooks_path == ".husky"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gate_log = tmp_path / "gate.log"
    gate_state = tmp_path / "gate-state"
    write_executable(
        bin_dir / "just",
        f"""#!/bin/sh
printf '%s\\n' "$*" >> {gate_log}
[ "$*" = "check" ] || exit 97
[ -f {gate_state} ]
""",
    )
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}

    refused = run(
        "git",
        "push",
        "origin",
        "HEAD:refs/heads/main",
        cwd=checkout,
        env=env,
        check=False,
    )
    assert refused.returncode != 0
    missing_ref = run(
        "git",
        "show-ref",
        "--verify",
        "refs/heads/main",
        cwd=remote,
        check=False,
    )
    assert missing_ref.returncode != 0

    gate_state.touch()
    run("git", "push", "origin", "HEAD:refs/heads/main", cwd=checkout, env=env)
    run("git", "show-ref", "--verify", "refs/heads/main", cwd=remote)
    assert gate_log.read_text().splitlines() == ["check", "check"]
