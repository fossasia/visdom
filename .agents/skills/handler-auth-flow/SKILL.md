---
name: handler-auth-flow
description: Add or modify Tornado handlers safely with auth, route ordering, and shared state conventions
---

# Skill: Handler and Auth Flow

## When to Use

Use this skill when changing `py/visdom/server/handlers/` or server routes.

## Core Workflow

1. Implement or modify handler classes in `web_handlers.py` or `socket_handlers.py`.
2. Keep `@check_auth` on protected handler methods.
3. In handler `initialize()`, copy required app attributes (do not refactor to `self.app`).
4. Register routes in `py/visdom/server/app.py` before fallback/index catch-alls.
5. Ensure both WebSocket and polling flows behave consistently.
6. Confirm browser-facing commands and payload keys remain stable.

## Guardrails

- Missing `@check_auth` is an auth bypass.
- Keep environment access sanitized and scoped to `env_path`.
- Avoid silent failure paths in handlers.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `py/visdom/server/app.py`
- `py/visdom/server/handlers/web_handlers.py`
- `py/visdom/server/handlers/socket_handlers.py`
- `py/visdom/server/handlers/base_handlers.py`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.
