---
name: performance-streaming
description: Optimize high-throughput visualization updates across server broadcast and frontend batching paths
---

# Skill: Performance for Streaming Updates

## When to Use

Use this skill when large update volume causes lag, dropped frames, or heavy CPU/network use.

## Core Workflow

1. Profile payload size and update frequency from Python client sends.
2. Prefer incremental updates/patches over full pane re-send.
3. Keep server broadcast fanout minimal and environment-scoped.
4. Preserve frontend batching/coalescing behavior for incoming pane updates.
5. Avoid unnecessary pane re-renders by preserving pane identity and memoization assumptions.

## Guardrails

- Do not trade correctness for speed in patch generation.
- Keep compare mode and normal mode both stable under load.
- Validate behavior in both WebSocket and polling modes.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `py/visdom/utils/server_utils.py`
- `py/visdom/server/handlers/socket_handlers.py`
- `js/main.js`
- `js/api/ApiProvider.js`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.
