---
name: callback-events
description: Implement and debug browser-to-Python callback routing for clicks, key presses, property updates, and close events
---

# Skill: Callback and Event Roundtrip

## When to Use

Use this skill when changing event callbacks or pane interactivity.

## Core Workflow

1. Register callback handlers via `register_event_handler()` on the Python side.
2. Ensure frontend emits correct event payloads (`event_type`, `target`, and event-specific fields).
3. Route browser events through socket command forwarding (`forward_to_vis`).
4. Keep server forwarding logic from browser socket to Python source sockets intact.
5. Validate event names/fields against existing callback contracts.

## Guardrails

- Callback handlers run in a background socket thread; avoid unsafe shared state writes.
- Do not rename event keys without coordinated client/server/docs updates.
- Preserve existing event types (`Click`, `KeyPress`, `PropertyUpdate`, `Close`, etc.).

## Documentation

- [Skill reference](references/REFERENCE.md)
- `py/visdom/__init__.py`
- `py/visdom/server/handlers/socket_handlers.py`
- `js/api/ApiProvider.js`
- `js/EventSystem.js`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.
