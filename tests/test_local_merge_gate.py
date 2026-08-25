import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parents[1]

MESSY_MODULE = 'import os\n\n\nx = {  "a" :1}\n'
TIDY_MODULE = '''"""Already lint-clean and already formatted."""\n\nX = {"a": 1}\n'''


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


def git_status(project: Path) -> str:
    return run("git", "status", "--porcelain", cwd=project).stdout


@pytest.fixture
def recipe_project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """The real justfile, driven with the real formatter but a stubbed project runner.

    ``uv tool run ...`` is delegated to the real uv so ``ruff`` genuinely runs
    over the temporary tree; only the project-scoped ``uv run -- ...`` calls
    (pyright, pytest) are stubbed, since the temporary tree has no venv.
    """
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(REPOSITORY_ROOT / "justfile", project / "justfile")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_uv = shutil.which("uv")
    assert real_uv is not None, "uv must be installed to drive the real lint recipe"
    write_executable(
        bin_dir / "uv",
        f"""#!/bin/sh
if [ "$1" = "tool" ]; then
  exec {real_uv} "$@"
fi
case "$*" in
  *pyright*) [ ! -f .fail-lint ] ;;
  *pytest*) [ ! -f .fail-tests ] ;;
  *) exit 0 ;;
esac
""",
    )
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return project, env


@pytest.fixture
def committed_recipe_project(
    recipe_project: tuple[Path, dict[str, str]],
) -> tuple[Path, dict[str, str]]:
    project, env = recipe_project
    run("git", "init", str(project), cwd=project.parent)
    run("git", "config", "user.name", "Gate Test", cwd=project)
    run("git", "config", "user.email", "gate@example.com", cwd=project)
    run("git", "add", "-A", cwd=project)
    run("git", "commit", "-m", "gate fixture", cwd=project)
    assert git_status(project) == ""
    return project, env


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


def test_check_over_a_clean_tree_leaves_the_tree_clean(
    committed_recipe_project: tuple[Path, dict[str, str]],
):
    project, env = committed_recipe_project
    tidy = project / "tidy_module.py"
    tidy.write_text(TIDY_MODULE)
    run("git", "add", "-A", cwd=project)
    run("git", "commit", "-m", "tidy module", cwd=project)
    assert git_status(project) == ""

    run("just", "check", cwd=project, env=env)

    assert git_status(project) == ""
    assert tidy.read_text() == TIDY_MODULE


def test_lint_reports_findings_without_rewriting_the_tree(
    committed_recipe_project: tuple[Path, dict[str, str]],
):
    project, env = committed_recipe_project
    messy = project / "messy_module.py"
    messy.write_text(MESSY_MODULE)
    run("git", "add", "-A", cwd=project)
    run("git", "commit", "-m", "messy module", cwd=project)

    result = run("just", "lint", cwd=project, env=env, check=False)

    assert result.returncode != 0
    assert "F401" in result.stdout + result.stderr
    assert messy.read_text() == MESSY_MODULE
    assert git_status(project) == ""


def test_format_recipe_is_still_the_way_to_fix_findings(
    committed_recipe_project: tuple[Path, dict[str, str]],
):
    project, env = committed_recipe_project
    messy = project / "messy_module.py"
    messy.write_text(MESSY_MODULE)
    run("git", "add", "-A", cwd=project)
    run("git", "commit", "-m", "messy module", cwd=project)

    run("just", "format", cwd=project, env=env)

    assert messy.read_text() != MESSY_MODULE
    assert "import os" not in messy.read_text()
    run("just", "lint", cwd=project, env=env)


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


def test_pre_commit_skips_when_the_formatter_is_not_installed(tmp_path: Path):
    """A clone made to publish from carries the hooks but not `node_modules`.

    `onevcs` gives the disposable clone it publishes through the lender's
    `core.hooksPath`, so both managed hooks run there — but nothing runs
    `pnpm install` in it, so the formatter `pre-commit` drives does not exist.
    Refusing the squash commit on that basis fails a publication over formatting
    that could not have been applied. Formatting is a convenience for a working
    checkout; the merge-path verifier is the pre-push gate.
    """
    checkout = tmp_path / "publication-clone"
    run("git", "init", str(checkout), cwd=tmp_path)
    run("git", "config", "user.name", "Gate Test", cwd=checkout)
    run("git", "config", "user.email", "gate@example.com", cwd=checkout)
    shutil.copytree(REPOSITORY_ROOT / ".husky", checkout / ".husky")
    run("git", "config", "core.hooksPath", ".husky", cwd=checkout)
    assert not (checkout / "node_modules").exists()

    (checkout / "notes.md").write_text("a tree nothing here can format\n")
    run("git", "add", "notes.md", cwd=checkout)
    committed = run(
        "git", "commit", "-m", "publication squash", cwd=checkout, check=False
    )

    assert committed.returncode == 0, committed.stdout + committed.stderr
