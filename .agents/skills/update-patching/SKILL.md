---
name: update-patching
description: Safely evolve incremental updates, jsonpatch generation, and pane update semantics
---

# Skill: Update and Patching System

## When to Use

Use this skill for changes around `/update`, incremental plot updates, or patch payloads.

## Core Workflow

1. Keep update entry points aligned (`update='append'|'replace'|'remove'` and heatmap update modes).
2. Update server patch generation logic in `py/visdom/utils/server_utils.py`.
3. Preserve `window` vs `window_update` message compatibility.
4. Ensure frontend patch application correctly updates pane content and `contentID`.
5. Validate behavior for line/scatter and heatmap row/column update paths.

## Guardrails

- Prefer patch payloads when smaller; do not force full-payload updates for small diffs.
- Keep update behavior deterministic across repeated calls.
- Do not break existing win-targeted update semantics.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `py/visdom/utils/server_utils.py`
- `py/visdom/server/handlers/web_handlers.py`
- `js/api/ApiProvider.js`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.
