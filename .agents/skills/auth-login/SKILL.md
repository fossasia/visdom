---
name: auth-login
description: Modify login/authentication paths safely for browser and Python client flows
---

# Skill: Authentication and Login

## When to Use

Use this skill when changing login screens, auth checks, cookie handling, or credential plumbing.

## Core Workflow

1. Keep server auth gate logic consistent with `check_auth`.
2. Preserve cookie-based session flow in Tornado handlers.
3. Maintain Python client authentication behavior (`Visdom(..., username=..., password=...)`).
4. Keep credential hashing and verification flow aligned between browser and server.
5. Keep cookie secret management in `env_path` stable.

## Guardrails

- Never weaken auth checks on handler methods.
- Never commit or hardcode credentials/cookie secrets.
- Treat auth changes as cross-cutting: server handlers, sockets, and client login must all remain compatible.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `py/visdom/server/handlers/base_handlers.py`
- `py/visdom/server/handlers/web_handlers.py`
- `py/visdom/server/app.py`
- `py/visdom/__init__.py`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.
