---
name: adding-pane
description: Step-by-step guide for adding a new visualization pane type to Visdom (client, server, frontend, tests)
---

# Skill: Adding a New Pane Type

## When to Use

Use this skill when adding a new visualization type (e.g., a new chart, widget, or media pane) to Visdom.

## Core Workflow

1. **Python Client** (`py/visdom/__init__.py`):
   - Add a new method to the `Visdom` class with `@pytorch_wrap`
   - Format data as `{"data": [{"type": "my_type", "content": ...}], ...}`
   - Call `self._send(msg)` to POST to `/events`

2. **Server** (`py/visdom/utils/server_utils.py`):
   - Add a new `elif ptype == "my_type":` branch in the `window()` function (around line 202)
   - Define what fields are stored in the window dict

3. **Frontend** (`js/panes/`):
   - Create `MyPane.js` following the pattern in `TextPane.js` or `ImagePane.js`
   - Use `forwardRef` + `React.memo` pattern from `Pane.js`

4. **Registration** (`js/settings.js`):
   - Add `my_type: MyPane` to the `PANES` object
   - Add default size to `PANE_SIZE`: `my_type: [width, height]`

5. **Type stubs** (`py/visdom/__init__.pyi`):
   - Add the method signature for type checking

6. **Demo** (`example/components/`):
   - Create a demo script exercising the new pane type
   - Import it in `example/demo.py`

7. **Tests** (`cypress/integration/`):
   - Add a Cypress test file for the new pane type

## Guardrails

- Always use the `@pytorch_wrap` decorator on new client methods
- Follow the `forwardRef` + `React.memo` pattern for pane components
- Import and register new panes in `js/settings.js`
- Never manually edit compiled files in `py/visdom/static/`
