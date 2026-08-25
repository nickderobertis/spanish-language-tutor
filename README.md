# spanish-language-tutor

## Local quality gate

Run `pnpm install` during setup. Its prepare step configures Git to use the
repository-managed hooks in `.husky`, including the staged-file pre-commit hook
and the pre-push merge gate.

`just check` is the complete secret-free deterministic gate. It checks lint,
formatting, imports, and types, then runs the complete pytest suite. The
pre-push hook runs this same command and refuses a push when it fails. The gate
does not require any value from `.env.template` and makes no paid provider
calls.

The gate proves local code, imports, types, tests, and Git hook wiring. A real
LiveKit/provider voice conversation is outside this deterministic boundary and
remains an operator-run manual check.
