---
name: python-client-api
description: Add or modify Visdom Python client methods with correct server/frontend parity and typing updates
---

# Skill: Python Client API Changes

## When to Use

Use this skill when adding or changing methods in `py/visdom/__init__.py`.

## Core Workflow

1. Add/update the `Visdom` method in `py/visdom/__init__.py`.
2. Keep `@pytorch_wrap` on public plotting APIs.
3. Build payloads through `self._send(...)` with consistent keys (`data`, `win`, `eid`, `opts`).
4. Update `py/visdom/__init__.pyi` for type stub parity.
5. If payload shape changes, update server handling (`py/visdom/utils/server_utils.py`) and pane rendering assumptions.
6. Add or update demo usage in `example/` and relevant Cypress tests.

## Guardrails

- Do not bypass `_send()` with ad-hoc transport logic.
- Keep backward compatibility for `win`, `env`, and `update` behavior.
- API changes must be reflected in docs and type stubs.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `py/visdom/__init__.py`
- `py/visdom/__init__.pyi`
- `py/visdom/utils/server_utils.py`
- `py/visdom/server/handlers/web_handlers.py`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.
