set fallback := true

run := "uv run --"
run-test := "uv run --"
run-lint := "uv tool run"

export PYTHONPATH := justfile_directory()

default:
    just check

check:
    just lint
    just test

install-hooks:
    git config core.hooksPath .husky


format *FILES='.':
    # https://docs.astral.sh/ruff/formatter/#sorting-imports
    {{run-lint}} ruff check --fix {{FILES}}
    {{run-lint}} ruff format {{FILES}}

# Read-only quality tier: reports findings, never rewrites the working tree.
lint *FILES='.':
    {{run-lint}} ruff check {{FILES}}
    {{run-lint}} ruff format --check {{FILES}}
    {{run}} pyright {{FILES}}

unsafe-fix:
    {{run-lint}} ruff check --fix --unsafe-fixes .
    {{run-lint}} ruff format .

start:
    LOG_LEVEL=info {{run}} python -m livekit.agents start language_tutor/agent.py --dev --log-level INFO

debug:
    LOG_LEVEL=debug {{run}} python -m livekit.agents start language_tutor/agent.py --dev --log-level DEBUG

sync:
    uv sync --group dev --frozen

create-token:
    lk token create --join --room language-tutor --identity candidate-user --valid-for "2h" | awk '/Access token:/ {print $3}'

creds:
    #!/usr/bin/env bash
    set -euo pipefail

    token=$(just create-token)
    echo "URL: ${LIVEKIT_URL}"
    echo "Token: ${token}"


test *OPTIONS:
    {{run}} pytest tests {{OPTIONS}}
