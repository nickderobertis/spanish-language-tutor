# spanish-language-tutor

A Spanish tutor with a Mexico City persona that talks with you over LiveKit,
corrects you briefly as you go, can search the web, can suggest a random
conversation topic, and writes a timestamped transcript of every session.

## Running the tutor

`just start` (info logs) and `just debug` (debug logs) launch the agent through
the supported LiveKit Agents CLI:

```
uv run -- python -m livekit.agents start language_tutor/agent.py --dev
```

`language_tutor/agent.py` exposes the `AgentServer` that CLI discovers. Hot
reload now comes from the LiveKit CLI (`lk agent dev`) rather than a `--watch`
flag on the Python process.

The realtime voice model is pinned explicitly to `gpt-realtime-2.1` rather than
left to the LiveKit plugin default, so conversation quality cannot drift when
the plugin bumps its own default.

## Local quality gate

Run `pnpm install` during setup. Its prepare step configures Git to use the
repository-managed hooks in `.husky`, including the staged-file pre-commit hook
and the pre-push merge gate.

`just check` is the complete secret-free deterministic gate. It checks lint,
formatting, imports, and types, then runs the complete pytest suite. The
pre-push hook runs this same command and refuses a push when it fails. The gate
does not require any value from `.env.template` and makes no paid provider
calls.

`just check` is read-only: running it over a clean tree leaves the tree clean,
so the content the gate judged is the content that gets pushed. Fixing lives in
the separate `just format` entry point (and `just unsafe-fix` for unsafe
autofixes), which is also what the pre-commit hook runs over staged files.

The gate proves local code, imports, types, tests, and Git hook wiring. A real
LiveKit/provider voice conversation is outside this deterministic boundary and
remains an operator-run manual check.
