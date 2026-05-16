---
name: websocket-flow
description: Guide for adding new WebSocket commands and API endpoints to Visdom
---

# Skill: WebSocket Flow & API Endpoints

## When to Use

Use this skill when adding new real-time WebSocket commands or HTTP API endpoints to Visdom.

## Adding a New WebSocket Command

1. **Socket handler** (`py/visdom/server/handlers/socket_handlers.py`):
   - Add `elif cmd == "my_command":` in `AnySocketHandlerOrWrapper.on_message()`
   - Use `broadcast()` to push updates to subscribers
   - Use `send_to_sources()` to push events to Python clients

2. **Frontend** (`js/api/ApiProvider.js`):
   - Add a `sendMyCommand` function that calls `sendSocketMessage({cmd: 'my_command', ...})`
   - Export it via the `ApiContext.Provider` value

3. **Message handling** (`js/api/ApiProvider.js`):
   - Add a `case 'my_response':` in `handleMessage()` switch statement

## Adding a New API Endpoint

1. **Handler** (`py/visdom/server/handlers/web_handlers.py`):
   - Create a new handler class extending `BaseHandler`
   - Implement `initialize(self, app)` copying required app attributes
   - Implement `post()` with `@check_auth` decorator

2. **Route** (`py/visdom/server/app.py`):
   - Add the route in `Application.__init__()` (lines 97-116)
   - Pattern: `(r"%s/my_endpoint" % self.base_url, MyHandler, {"app": self})`
   - Place **before** the catch-all `IndexHandler` route

3. **Client** (`py/visdom/__init__.py`):
   - Add a method calling `self._send(msg, endpoint="my_endpoint")`

## Guardrails

- Every socket feature must work in both WebSocket and polling modes
- All handlers must use `@check_auth` decorator
- Copy required app attributes in `initialize()` — do not use `self.app`
- Test both `functional-test` and `functional-test-polling` CI jobs
