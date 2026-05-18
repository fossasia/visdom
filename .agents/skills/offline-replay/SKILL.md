---
name: offline-replay
description: Extend or debug offline logging and replay workflows without requiring a live browser session
---

# Skill: Offline Log and Replay

## When to Use

Use this skill for `offline=True`, log generation, and `replay_log(...)` behavior.

## Core Workflow

1. Keep offline logging paths in the Python client stable and append-safe.
2. Ensure log serialization retains enough data to reconstruct panes.
3. Verify replay sends equivalent commands through normal server paths.
4. Preserve compatibility with existing historical log files.
5. Document any replay format changes clearly.

## Guardrails

- Do not introduce replay-only behavior diverging from live send behavior.
- Keep log format backward-compatible where possible.
- Surface parse/replay errors clearly.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `py/visdom/__init__.py`
- `example/`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.
