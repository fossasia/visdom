<!-- SPDX-License-Identifier: Apache-2.0
     https://www.apache.org/licenses/LICENSE-2.0 -->

# AGENTS instructions

## Project Overview

Visdom is a live data visualization tool for creating, organizing, and sharing rich visualizations of scientific experiments. It provides a Python client library, a Tornado-based web server, and a React frontend.

- **Repository:** [fossasia/visdom](https://github.com/fossasia/visdom)
- **Version:** `0.2.4` (stored in `py/visdom/VERSION`)
- **License:** Apache 2.0
- **Python:** >= 3.8

## Core Repo Rules

- Format Python with **Black** (`black py`, version `23.1.0`). CI enforces this.
- Format JS/CSS/JSON with **Prettier** (v2.6.2). Lint JS with **ESLint** (`npm run lint`).
- **Never manually edit** files in `py/visdom/static/` — these are built by webpack and downloaded by `build.py`. The GitHub Action compiles them automatically on master.
- **Never edit** legacy Lua/Torch code in `th/` — deprecated since v0.1.8.4.
- **Never commit** secrets, credentials, tokens, or `COOKIE_SECRET` files.
- **Never push** directly to `master` — use feature branches and pull requests.
- **Never skip** pre-commit hooks (`--no-verify`) without explicit approval.
- Apache License header required on all new files (see `context/backend.md` for templates).

## Important Pitfalls

### Handler Initialization Pattern

Every HTTP handler in `web_handlers.py` manually copies attributes from `app` in `initialize()`. Do **not** refactor this to use `self.app` without explicit approval.

### `check_auth` Decorator

All HTTP handler `post()`/`get()` methods must use `@check_auth` from `server_utils.py`. Forgetting this creates an authentication bypass.

### WebSocket vs Polling Duality

Every socket feature must work in **both** WebSocket and polling modes. CI tests both. If you add WebSocket handling, verify it also works via the `*Wrap` polling handlers.

### Mutable State in `main.js`

The frontend contains intentional direct state mutation (`storeData.layout = layout`) for performance with `relayout()`. Do not "fix" this.

### XSS via `TextPane`

`TextPane.js` renders user content using `innerHTML` — this is by design. Never expose a Visdom server to untrusted networks without authentication.

### Path Traversal in Environment Names

Environment names construct filesystem paths. Always sanitize via `escape_eid()` and verify results are within `env_path`.

## Mandatory Workflows

### Setup

```bash
pip install -e .                      # Python install from source
pip install -r test-requirements.txt  # Test dependencies
yarn && yarn run build                # Frontend build
pip install pre-commit && pre-commit install  # Pre-commit hooks
```

### Testing

Always start a fresh visdom server on port 8098 before running Cypress:

```bash
visdom -port 8098 -env_path /tmp
npm run test:init                     # Generate baseline screenshots
npm run test                          # Run all Cypress tests
```

### Pre-commit

```bash
pre-commit run --all-files
```

Hooks: trailing whitespace, end-of-file fixer, YAML validation, large file detection, Black, Prettier.

### Pull Request Checklist

1. Fork the repo and create your branch from `master`.
2. Add Cypress tests for new code.
3. Update README for API changes; update `__init__.pyi` for Python interface changes.
4. Do **not** manually commit files in `py/visdom/static/`.
5. Run `npm run lint` and `black py` before submitting.
6. Fill in the PR template (`PULL_REQUEST_TEMPLATE.md`).

## Boundaries

### Ask First

- Changes to server API endpoints or message protocol
- New Python or Node.js dependencies
- Changes to environment persistence format or authentication
- Large cross-component refactors

### Never

- Break backward compatibility of the Python client API without discussion
- Use destructive git operations unless explicitly requested
- Manually edit `download.sh` — superseded by `py/visdom/server/build.py`

## Detailed Context & Skills

- **Context:** `context/` — architecture, frontend, backend, testing
- **Skills:** `skills/` — adding-pane, websocket-flow, cypress-testing, release-process
