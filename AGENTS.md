<!-- SPDX-License-Identifier: Apache-2.0
     https://www.apache.org/licenses/LICENSE-2.0 -->

# AGENTS instructions

Visdom: Python client + Tornado server + React frontend for live data visualization.
Version `0.2.4` · Python >= 3.8 · Apache 2.0

## Setup

- Install Python: `pip install -e . && pip install -r test-requirements.txt`
- Build frontend: `yarn && yarn run build`
- Install hooks: `pip install pre-commit && pre-commit install`

## Code Style

- Format Python: `black py` (v23.1.0, CI-enforced)
- Lint JS: `npm run lint`
- Format JS/CSS/JSON: Prettier (v2.6.2)
- Add Apache License headers to all new files (see `context/backend.md`)

## Do Not

- Edit files in `py/visdom/static/` — auto-built by CI
- Edit legacy Lua/Torch code in `th/`
- Commit secrets, credentials, or `COOKIE_SECRET`
- Push directly to `master`
- Skip pre-commit hooks (`--no-verify`)

## Pitfalls

- Handlers in `web_handlers.py` copy app attributes in `initialize()` — do not refactor to `self.app`
- Always decorate handler methods with `@check_auth` — omitting it creates an auth bypass
- Every socket feature must work in both WebSocket and polling modes
- Do not "fix" direct state mutation in `main.js` (`storeData.layout = layout`) — intentional
- `TextPane.js` uses `innerHTML` by design — do not expose server without auth
- Sanitize environment names via `escape_eid()`, verify paths stay within `env_path`

## Testing

- Start server: `visdom -port 8098 -env_path /tmp`
- Baseline: `npm run test:init`
- Run tests: `npm run test`
- Pre-commit: `pre-commit run --all-files`

## PR Checklist

- Branch from `master`, add Cypress tests for new code
- Update `README` for API changes, `__init__.pyi` for interface changes
- Run linters, do not commit `py/visdom/static/`

## Ask Before

- Changing API endpoints, message protocol, or auth
- Adding Python or Node.js dependencies
- Large cross-component refactors

## Context & Skills

- `context/` — architecture, backend, frontend, testing
- `skills/` — adding-pane, websocket-flow, cypress-testing, release-process
