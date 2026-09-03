---
name: environment-views
description: Work on environments, compare mode, persistence, and view layouts across server and frontend
---

# Skill: Environments and Views

## When to Use

Use this skill for `save`, `fork`, `delete`, compare flows, and layout/view behavior.

## Core Workflow

1. Trace environment behavior across:
   - Python client env methods (`save`, `fork_env`, `delete_env`, `get_env_list`)
   - Server handlers (`/env`, `/compare`, `/save`, `/delete_env`, `/fork_env`)
   - Frontend env controls and layout application
2. Keep environment persistence format stable (`jsons` + `reload` structure).
3. Maintain compare semantics: merge windows by title with clear legend prefixes.
4. Keep view layout storage and reload behavior consistent with existing format.

## Guardrails

- Preserve hierarchical env naming assumptions based on `_`.
- Do not break old env JSON compatibility.
- Ensure env operations behave the same in WebSocket and polling modes.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `py/visdom/__init__.py`
- `py/visdom/utils/server_utils.py`
- `py/visdom/server/handlers/web_handlers.py`
- `js/topbar/EnvControls.js`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.
