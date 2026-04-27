<!-- SPDX-License-Identifier: Apache-2.0
     https://www.apache.org/licenses/LICENSE-2.0 -->

# AGENTS instructions

## Project Overview

Visdom is a live data visualization tool for creating, organizing, and sharing rich visualizations of scientific experiments. It provides a Python client library, a Tornado-based web server, and a React frontend. Visualizations include Plotly charts, images, text/HTML, audio, video, SVG, network graphs, t-SNE embeddings, and more.

- **Repository:** [fossasia/visdom](https://github.com/fossasia/visdom) (originally Facebook Research)
- **Version:** `0.2.4` (stored in `py/visdom/VERSION`)
- **License:** Apache 2.0
- **Python:** >= 3.8
- **Authors:** Facebook, Inc., @JackUrb, @da-h, @lvdmaaten, @ajabri (see `AUTHORS`)

## Environment Setup

### Python (install from source)

```bash
pip install -e .                      
pip install -r test-requirements.txt  
```

### Node.js (for frontend/UI work)

```bash
yarn            
yarn run build  
```

### Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

Hooks (`.pre-commit-config.yaml`): trailing whitespace, end-of-file fixer, YAML validation, large file detection, **Black** (v22.10.0, Python), **Prettier** (v2.6.2, for CSS/JS/JSON).

### Start the server

```bash
visdom                     
python -m visdom.server    
```

On first run, visdom downloads external JS/CSS/font dependencies from CDNs (Plotly, jQuery, Bootstrap, MathJax, etc.) into `py/visdom/static/`. This is handled by `download_scripts()` in `py/visdom/server/build.py`. The download is skipped if the cached version matches `py/visdom/VERSION`.

## Commands

| Command | Purpose |
|---------|---------|
| `visdom` | Start server (default port 8097) |
| `visdom -port <PORT>` | Start server on custom port |
| `visdom -enable_login` | Start with authentication |
| `visdom -readonly` | Start in read-only mode |
| `visdom -bind_local` | Restrict access to localhost only |
| `visdom -eager_data_loading` | Pre-load all envs on startup |
| `visdom -use_frontend_client_polling` | Use polling instead of WebSockets |
| `python example/demo.py` | Run full feature demo |
| `npm run build` / `yarn run build` | Build frontend (production) |
| `npm run dev` / `yarn run dev` | Build frontend (watch mode, auto-rebuild) |
| `npm run lint` | Lint JavaScript (ESLint) |
| `npm run lint:fix` | Lint + auto-fix JavaScript |
| `black py` | Format Python (requires `black==23.1`) |
| `pre-commit run --all-files` | Run all pre-commit hooks |
| `npm run test:init` | Generate Cypress baseline screenshots |
| `npm run test` | Run all Cypress tests (CLI) |
| `npm run test:gui` | Run Cypress tests (interactive GUI) |
| `npm run test:visual` | Run visual regression tests only |

**Testing workflow:** Always start a fresh visdom server on port 8098 before running Cypress:

```bash
visdom -port 8098 -env_path /tmp  
npm run test:init                 
npm run test                   
```

## Server CLI Arguments

| Flag | Description | Default |
|------|-------------|---------|
| `-port` | Server port | `8097` |
| `--hostname` | Server hostname | `localhost` |
| `-base_url` | Base URL prefix (must start with `/`, must not end with `/`) | `/` |
| `-env_path` | Path to environment state directory | `~/.visdom/` |
| `-logging_level` | Logging level (name or int, e.g. `INFO`, `20`) | `INFO` |
| `-readonly` | Start in read-only mode | `false` |
| `-enable_login` | Require username/password authentication | `false` |
| `-force_new_cookie` | Reset session cookie (requires `-enable_login`) | `false` |
| `-bind_local` | Only listen on `127.0.0.1` | `false` |
| `-eager_data_loading` | Pre-load all env JSON files on startup (vs. lazy) | `false` |
| `-use_frontend_client_polling` | Frontend uses HTTP polling instead of WebSockets | `false` |

The server sets `max_buffer_size=1024**3` (~1 GB) on the listening socket for large payloads.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `VISDOM_USE_ENV_CREDENTIALS` | Set to `1` to use env-based authentication instead of terminal prompt |
| `VISDOM_USERNAME` | Username (required when `VISDOM_USE_ENV_CREDENTIALS=1`) |
| `VISDOM_PASSWORD` | Password (required when `VISDOM_USE_ENV_CREDENTIALS=1`) |
| `VISDOM_COOKIE` | Cookie secret (used if `COOKIE_SECRET` file is missing or `-force_new_cookie` is set) |
| `HOSTNAME` | Overrides default hostname in the server's startup URL output |

## Repository Structure

```
visdom/
├── py/visdom/                           — Python package (client + server)
│   ├── __init__.py                      — Visdom client class: 2,594 lines, 40+ visualization methods
│   ├── __init__.pyi                     — Type stubs (PEP 484) for the client API
│   ├── py.typed                         — PEP 561 marker (package supports type checking)
│   ├── VERSION                          — Version string ("0.2.4")
│   ├── server/                          — Tornado web server
│   │   ├── app.py                       — Application class: routes, state management, user settings
│   │   ├── run_server.py                — CLI entry point: arg parsing, auth setup, ioloop.start()
│   │   ├── build.py                     — download_scripts(): fetches Plotly, jQuery, Bootstrap, MathJax, etc.
│   │   ├── defaults.py                  — DEFAULT_PORT=8097, DEFAULT_ENV_PATH=~/.visdom/, etc.
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   └── handlers/                    — HTTP + WebSocket request handlers
│   │       ├── base_handlers.py         — BaseHandler, BaseWebSocketHandler (with auth cookie support)
│   │       ├── web_handlers.py          — PostHandler, UpdateHandler, CloseHandler, EnvHandler, etc.
│   │       └── socket_handlers.py       — SocketHandler/Wrap (read-only), VisSocketHandler/Wrap (write)
│   ├── utils/
│   │   ├── shared_utils.py              — warn_once, get_rand_id, get_new_window_id, ensure_dir_exists, get_visdom_path
│   │   └── server_utils.py              — check_auth, serialize_env, LazyEnvData, broadcast, compare_envs,
│   │                                      register_window, window, hash_password, set_cookie, stringify
│   ├── user/
│   │   └── style.css                    — Default user stylesheet (empty)
│   ├── extra_deps/
│   │   └── __init__.py                  — Placeholder for bhtsne (Barnes-Hut t-SNE) optional dependency
│   └── static/                          — Compiled frontend assets (AUTO-GENERATED — do NOT edit)
│       ├── js/main.js                   — Webpack output from js/ sources
│       ├── js/main.js.map               — Source map
│       ├── js/*.min.js                  — Downloaded CDN deps (Plotly, jQuery, Bootstrap, React, etc.)
│       ├── css/                          — Downloaded CSS (Bootstrap, react-grid-layout, react-resizable)
│       └── fonts/                        — Downloaded Bootstrap Glyphicon fonts
│
├── js/                                  — React frontend source (926 lines in main.js)
│   ├── main.js                          — App entry: grid layout, env management, pane rendering
│   ├── api/
│   │   ├── ApiContext.js                — React Context for API state
│   │   ├── ApiProvider.js               — 310 lines: WebSocket connection, message routing, env queries
│   │   └── Legacy.js                    — Polling fallback for environments without WebSocket support
│   ├── panes/
│   │   ├── Pane.js                      — Base pane: title bar, resize handle, close/download buttons
│   │   ├── PlotPane.js                  — Plotly chart renderer (scatter, line, bar, heatmap, surface, etc.)
│   │   ├── TextPane.js                  — Text/HTML rendering with innerHTML
│   │   ├── ImagePane.js                 — Image display with zoom (ctrl+scroll), pan (alt+scroll), click coords
│   │   ├── EmbeddingsPane.js            — t-SNE visualization with D3 lasso selection for subset refinement
│   │   ├── NetworkPane.js               — Network graph rendering using D3 force-directed layout
│   │   ├── PropertiesPane.js            — Interactive form: text, number, button, checkbox, select
│   │   └── PropertyItem.js              — Individual property widget
│   ├── topbar/
│   │   ├── ConnectionIndicator.js       — Server connection status indicator
│   │   ├── EnvControls.js               — Environment selector, compare, clear, manage
│   │   ├── FilterControls.js            — Regex-based window title filter
│   │   └── ViewControls.js              — View save/load/repack controls
│   ├── modals/
│   │   ├── EnvModal.js                  — Environment management dialog (fork, save, delete)
│   │   └── ViewModal.js                 — View management dialog
│   ├── EventSystem.js                   — Custom event dispatching system
│   ├── settings.js                      — UI preferences storage
│   ├── lasso.js                         — D3-based lasso selection for embeddings
│   ├── Width.js                         — Responsive width detection helper
│   └── util.js                          — Frontend utilities
│
├── cypress/                             — End-to-end + visual regression tests (Cypress 9)
│   ├── integration/
│   │   ├── basic.js                     — Server connection, environment selection
│   │   ├── pane.js                      — Window/pane CRUD operations
│   │   ├── text.js                      — Text pane functionality
│   │   ├── image.js                     — Image pane operations
│   │   ├── properties.js               — Interactive property widget tests
│   │   ├── modal.js                     — Modal dialog interactions
│   │   ├── misc.js                      — Miscellaneous feature tests
│   │   ├── screenshots.init.js          — Baseline screenshot capture (run first)
│   │   └── screenshots.js              — Visual regression comparison
│   ├── plugins/                         — Cypress plugins (pixelmatch for image comparison)
│   └── support/                         — Support files and custom commands
│
├── example/                             — Demo scripts
│   ├── demo.py                          — Main demo: runs all component demos sequentially
│   ├── mnist-embeddings.py              — MNIST t-SNE embeddings example
│   ├── components/                      — Modular demo components
│   │   ├── text.py                      — Text: basic, update, callbacks, close, fork
│   │   ├── image.py                     — Image: basic, callback, JPEG, history, grid, SVG
│   │   ├── plot_line.py                 — Line: basic, multi, WebGL, updates, stacked area, dual Y-axis
│   │   ├── plot_scatter.py              — Scatter: basic, update, 3D, custom markers/colors, text labels
│   │   ├── plot_bar.py                  — Bar: basic, stacked, histogram, pie, sunburst
│   │   ├── plot_surface.py              — Surface, heatmap, contour with append/replace/remove
│   │   ├── plot_special.py              — Boxplot, quiver, mesh, network graph
│   │   ├── properties.py               — Properties: basic, callbacks
│   │   └── misc.py                      — Matplotlib, plotlyplot, LaTeX, video, audio, embeddings
│   └── <issue-number>.py               — Issue-specific reproduction/demonstration scripts
│
├── th/                                  — Legacy Lua/Torch client (DEPRECATED since v0.1.8.4 — do not touch)
│
├── .github/
│   ├── workflows/
│   │   ├── process-changes.yml          — PR checks: lint-js, lint-py, build, Cypress (visual + functional)
│   │   ├── update-js-build-files.yml    — Auto-compile main.js on push to master (when js/** changes)
│   │   ├── pypi.yml                     — Auto-publish to PyPI on push to master (when VERSION changes)
│   │   └── issue-scripts.yml            — Auto-respond to "assign me" comments on issues
│   └── actions/prepare/
│       └── action.yml                   — Shared CI setup: Node 16, pip cache, npm cache, build artifacts
│
├── webpack.common.js                    — Shared webpack config: entry=js/main.js, output=py/visdom/static/js/main.js
├── webpack.dev.js                       — Development webpack (source maps, no minification)
├── webpack.prod.js                      — Production webpack (minified, optimized)
├── setup.py                             — Python package setup: deps, entry_points, find_packages(where="py")
├── package.json                         — Node.js deps and scripts (React 17, Webpack 5, Cypress 9, etc.)
├── yarn.lock                            — Yarn lockfile
├── .eslintrc                            — ESLint config: eslint:recommended + React + jsx-a11y + Prettier
├── .prettierrc                          — Prettier config (singleQuote, semi, trailingComma, tabWidth)
├── .pre-commit-config.yaml              — Pre-commit hooks: Black, Prettier, whitespace, YAML, large files
├── test-requirements.txt                — Python test deps: matplotlib, numpy, av, torch
├── download.sh                          — Legacy manual script download (superseded by build.py)
├── CONTRIBUTING.md                      — Contribution guidelines + troubleshooting
├── CODE_OF_CONDUCT.md                   — Contributor Covenant v1.4
├── PULL_REQUEST_TEMPLATE.md             — PR template with checklist
├── AUTHORS                              — Significant contributors
├── LICENSE                              — Apache 2.0
└── MANIFEST.in                          — sdist manifest: VERSION, py.typed, *.pyi, static/*
```

## Architecture

### Components

1. **Python Client** (`py/visdom/__init__.py`, 2,594 lines) — The `Visdom` class provides 40+ visualization methods. Communicates with the server via HTTP POST (using `requests.Session`) and WebSocket (`websocket-client`). Supports PyTorch tensor auto-conversion via the `@pytorch_wrap` decorator, which calls `_to_numpy()` to handle `torch.Tensor` and `torch.nn.Parameter` inputs. Also supports offline mode (log to file without server) and a polling fallback for restricted networks.

2. **Tornado Server** (`py/visdom/server/`) — `Application` class (subclass of `tornado.web.Application`) manages:
   - `self.state` — Dict mapping environment IDs to window data (loaded via `LazyEnvData` for on-demand loading, or eagerly)
   - `self.subs` — Dict of read-only WebSocket subscriber connections
   - `self.sources` — Dict of write-enabled WebSocket source connections
   - `self.layouts` — JSON string of saved view layouts
   - `self.user_settings` — User CSS from platform-specific config dirs
   - Authentication via Tornado's secure cookies (`user_password`, SHA256-hashed)

3. **React Frontend** (`js/`, compiled by Webpack 5 into `py/visdom/static/js/main.js`) — Single-page application:
   - **React 17** with functional components and hooks (`ApiProvider` uses `useEffect`, `useRef`, `useState`)
   - **Plotly.js** (v2.11.1, loaded via CDN into `py/visdom/static/js/`) for all chart rendering
   - **ReactGridLayout** (v0.16.6) for draggable/resizable window grid
   - **D3** (selection, drag, zoom, polygon) for network graph force layout and lasso selection
   - **Three.js** (v0.105.2) for 3D mesh/surface rendering
   - **MathJax** (v2.7.5) for LaTeX rendering in text panes
   - **Savitzky-Golay filter** (`ml-savitzky-golay-generalized`) for interactive line plot smoothing

### Data Flow

```
Python Client  ──HTTP POST /events──▶  Tornado Server  ──WebSocket──▶  React Frontend (Browser)
      │                                      │
      │◀──WebSocket /vis_socket──────────────│  (event callbacks: Close, KeyPress, PropertyUpdate, Click)
      │                                      │
      │                               JSON files (~/.visdom/)
      │                                 ├── main.json
      │                                 ├── <env>.json
      │                                 └── view/layouts.json
```

### API Endpoints

Defined in `py/visdom/server/app.py` (lines 97-116). All endpoints are prefixed with `base_url`.

| Endpoint | Handler | Method | Purpose |
|----------|---------|--------|---------|
| `/events` | `PostHandler` | POST | Create new windows / send visualization data |
| `/update` | `UpdateHandler` | POST | Update existing window data (append/replace/remove) |
| `/close` | `CloseHandler` | POST | Close a window |
| `/socket` | `SocketHandler` | WebSocket | Read-only client connection (subscribers) |
| `/socket_wrap` | `SocketWrap` | POST | Polling fallback for read-only connections |
| `/vis_socket` | `VisSocketHandler` | WebSocket | Write-enabled client connection (sources) |
| `/vis_socket_wrap` | `VisSocketWrap` | POST | Polling fallback for write-enabled connections |
| `/env/<eid>` | `EnvHandler` | GET/POST | Load or create an environment |
| `/compare/<eid>` | `CompareHandler` | GET/POST | Compare multiple environments (comma-separated) |
| `/save` | `SaveHandler` | POST | Persist environment state to disk as JSON |
| `/win_exists` | `ExistsHandler` | POST | Check if a window exists |
| `/win_data` | `DataHandler` | POST | Get/set raw window data |
| `/delete_env` | `DeleteEnvHandler` | POST | Delete an environment (irreversible) |
| `/env_state` | `EnvStateHandler` | POST | List all environment IDs |
| `/fork_env` | `ForkEnvHandler` | POST | Clone an environment |
| `/error/<eid>` | `ErrorHandler` | POST | Client error logging |
| `/user/<path>` | `UserSettingsHandler` | GET/POST | Serve user config/CSS |
| `/<path>` | `IndexHandler` | GET | Serve index.html, static assets, handle login POST |

### Window Types

The server recognizes the following pane types (see `window()` in `py/visdom/utils/server_utils.py`):

| Type | Handler | Description |
|------|---------|-------------|
| `plot` | `PlotPane.js` | All Plotly-based charts (scatter, line, bar, heatmap, surface, contour, etc.) |
| `image` | `ImagePane.js` | Single image with zoom/pan and coordinate tracking |
| `image_history` | `ImagePane.js` | Image with slider to browse stored history |
| `text` | `TextPane.js` | Arbitrary HTML/text content |
| `properties` | `PropertiesPane.js` | Interactive form (text, number, button, checkbox, select) |
| `network` | `NetworkPane.js` | D3 force-directed graph with directed/undirected edges |
| `embeddings` | `EmbeddingsPane.js` | t-SNE visualization with lasso-based subset refinement |

### Python Client API

The `Visdom` class (`py/visdom/__init__.py`) provides these method categories:

**Connection & State:**
`check_connection()`, `save(envs)`, `close(win, env)`, `delete_env(env)`, `fork_env(prev_eid, eid)`, `get_env_list()`, `win_exists(win, env)`, `get_window_data(win, env)`, `set_window_data(data, win, env)`, `replay_log(log_filename)`, `update_window_opts(win, opts, env)`

**Event Handling:**
`register_event_handler(handler, target)`, `clear_event_handlers(target)`

**Basic Visualizations:**
`text()`, `image()`, `images()`, `audio()`, `video()`, `svg()`, `matplot()`, `plotlyplot()`, `properties()`, `embeddings()`

**Plotting (Plotly-based):**
`scatter()`, `line()`, `bar()`, `histogram()`, `heatmap()`, `boxplot()`, `surf()`, `contour()`, `quiver()`, `stem()`, `mesh()`, `pie()`, `sunburst()`, `dual_axis_lines()`, `graph()`

Most plotting methods support `update` parameter (`'append'`, `'replace'`, `'remove'`) for efficient incremental updates, and `name` parameter to target specific traces.

### Data Storage

- **Location:** `~/.visdom/` (default, configurable via `-env_path`)
- **Format:** JSON files per environment
  - `main.json` — Default environment
  - `<env_name>.json` — Per-environment state (window data keyed by window ID)
  - `view/layouts.json` — Saved window layout positions/sizes
  - `COOKIE_SECRET` — Session cookie secret file (when auth enabled)
- **Lazy loading:** `LazyEnvData` class (`py/visdom/utils/server_utils.py`) implements `collections.abc.Mapping` to defer JSON parsing until first access. Use `-eager_data_loading` to pre-load all envs at startup.
- **Env naming:** `/` characters in environment names are escaped to `_` (see `escape_eid()`). Environments are hierarchically organized by the first `_` in the UI. Never use raw user input as a filename — always pass through `escape_eid()` and verify the result is within `env_path`.
- **User CSS:** Platform-specific config directories:
  - Linux: `~/.config/visdom/style.css`
  - macOS: `~/Library/Preferences/visdom/style.css`
  - Windows: `%APPDATA%/visdom/style.css`
  - Project-specific: `<env_path>/style.css`

### Authentication

- **Cookie-based** with Tornado's `set_secure_cookie` / `get_secure_cookie`
- Password is **double SHA256-hashed** (`hash_password(hash_password(password))`) and compared server-side
- Cookie name: `user_password`
- Cookie secret stored in `~/.visdom/COOKIE_SECRET` file
- `check_auth` decorator on all handlers returns HTTP 400 if login is enabled and user is not authenticated
- SJCL (Stanford JavaScript Crypto Library) is used client-side for password hashing in the browser login form

### Communication Modes

1. **WebSocket** (default) — Client connects via `/vis_socket` (write) or `/socket` (read-only). Server pushes window updates, layout changes, and env updates in real-time.
2. **Polling** (fallback) — Enabled with `-use_frontend_client_polling`. Client polls `/vis_socket_wrap` or `/socket_wrap` via POST. Same API semantics, higher latency.

### Offline Mode

Set `offline=True` and `log_to_filename='path/to/log'` on the `Visdom` client. All visualization calls are logged to file instead of sent to a server. Replay later with `vis.replay_log('path/to/log')`.

## CI/CD Workflows

### `process-changes.yml` (on: pull_request)

| Job | Description |
|-----|-------------|
| **lint-js** | ESLint check (Node 16) |
| **lint-py** | Black formatting check (v23.1.0 via `psf/black` action) |
| **install-and-build** | Build JS from PR, upload `main.js` + `main.js.map` as artifacts |
| **visual-regression-test-init** | Cypress `test:init` against **base branch** build (baseline screenshots) |
| **visual-regression-test** | Cypress `screenshots.js` against **PR** build (compare to baseline) |
| **functional-test (websocket)** | Cypress functional tests on **Python 3.8, 3.9, 3.10** (matrix) |
| **functional-test (polling)** | Cypress functional tests with `-use_frontend_client_polling` flag |

CI uses `visdom -port 8098 -env_path /tmp` for all test runs (clean state, non-default port).

### `update-js-build-files.yml` (on: push to master, if js/** changed)

Auto-compiles `main.js` and `main.js.map` from `js/` sources, commits them to master. This means **you should never manually commit compiled static JS files**.

### `pypi.yml` (on: push to master, if py/visdom/VERSION changed)

Creates a GitHub release (`v<VERSION>`) with auto-generated release notes, then builds and publishes to PyPI using `python setup.py sdist`.

### `issue-scripts.yml` (on: issue_comment)

Auto-responds to "please assign" / "assign me" comments explaining that the project doesn't assign issues to external contributors.

## Coding Standards

### Python

- Follow **PEP 8**. Format with **Black** (`black py`, version `23.1`). CI enforces this.
- **80 character** line length.
- **Apache License header** on all new files:

  **Python:**
  ```python
  #!/usr/bin/env python3

  # Copyright 2017-present, The Visdom Authors
  # All rights reserved.
  #
  # This source code is licensed under the license found in the
  # LICENSE file in the root directory of this source tree.
  ```

  **JavaScript:**
  ```javascript
  /**
   * Copyright 2017-present, The Visdom Authors
   * All rights reserved.
   *
   * This source code is licensed under the license found in the
   * LICENSE file in the root directory of this source tree.
   *
   */
  ```
- Python **>= 3.8** compatibility. Every file that uses `Mapping` or `Sequence` must use this pattern:

  ```python
  try:
      from collections.abc import Mapping, Sequence  # Python >= 3.8
  except ImportError:
      from collections import Mapping, Sequence  # Python <= 3.7
  ```
- All `Visdom` methods use `@pytorch_wrap` decorator for automatic PyTorch tensor → numpy conversion.
- `assert` statements are used for input validation in the client (not production server paths).
- Prefer `warnings.warn()` via `warn_once()` for deprecation and one-time warnings.
- Use `requests.Session` for HTTP connections (session is lazily created on first use).

### JavaScript

- **ESLint** (`.eslintrc`): `eslint:recommended` + React + jsx-a11y + Prettier integration.
  - **Max line length:** 80 (URLs and strings exempt).
  - **Import sorting** enforced as error (`simple-import-sort/imports`, `simple-import-sort/exports`).
  - **No console** (warn level).
  - **Plotly** declared as `readonly` global (loaded via CDN, not bundled).
  - `ignore-generated-and-nolint` plugin skips generated files.
- **Prettier** (`.prettierrc`): explicit formatting options are configured, including `singleQuote`, `semi`, and `trailingComma`.
- **Babel** transpilation: `@babel/preset-env` + `@babel/preset-react` + `class-properties` plugin.
- **Webpack 5** config:
  - Entry: `js/main.js`
  - Output: `py/visdom/static/js/main.js`
  - Polyfills: `stream-browserify`, `browserify-zlib`, `util`, `https-browserify`, `stream-http`, `whatwg-fetch`
  - `net` and `dns` are explicitly set to `false` (not available in browser)
  - Banner plugin adds `@generated` comment to output
- **Never manually edit** files in `py/visdom/static/`. The GitHub Action compiles them automatically on master. For PR branches, the CI builds and stores artifacts.

### Version Numbering

- Follow [Semantic Versioning](https://semver.org/).
- Version is stored in `py/visdom/VERSION` (single-line plaintext).
- `setup.py` reads this file at build time.
- Changing VERSION on master auto-triggers the PyPI publish workflow.
- `py/visdom/server/build.py` uses the version to track whether CDN dependencies need re-downloading.

## Testing Standards

- **Framework:** Cypress 9 (end-to-end and visual regression).
- **No Python unit test suite** — Python client behavior is validated via demo scripts and Cypress end-to-end tests that exercise the full client-server-frontend stack.
- **Test server:** Always use a fresh server on port `8098` with `-env_path /tmp` to avoid state interference.
- **Visual regression:** Uses `pixelmatch` (in `cypress/plugins/`) for pixel-level screenshot comparison. Run `npm run test:init` first to establish baseline, then `npm run test:visual`.
- **Functional tests:** Exercise window creation, pane operations, text, image, properties, and modal interactions. CI runs these in both WebSocket and polling modes.
- **CI Python versions:** 3.8, 3.9, 3.10 (matrix strategy).
- **Regression validation:** Run `python example/demo.py` on both your branch and a clean branch, visually confirm no differences.
- **Test dependencies:** `test-requirements.txt` (matplotlib, numpy, av, torch-cpu). CI also uses the Cypress GitHub Action.

## Common Pitfalls and Gotchas

AI agents **must** be aware of these project-specific traps:

### Handler Initialization Pattern

Every HTTP handler in `web_handlers.py` manually copies attributes from the `app` object in `initialize()`. This is **not** DRY — it's a known pattern. When adding a new handler:

```python
class MyHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled
```

Do **not** refactor this to use `self.app` without explicit approval — it would affect all existing handlers.

### Mutable State in `main.js` (Frontend)

The frontend `main.js` contains non-conventional React patterns (marked with `TODO` comments). Specifically:

```javascript
// Direct mutation of storeData.layout (lines ~553, ~568):
storeData.layout = layout;  // bypasses React state
```

This is intentional for performance with `relayout()`. Do not "fix" this without understanding the full layout pipeline.

### `check_auth` Decorator

All HTTP handler `post()`/`get()` methods must use `@check_auth` from `server_utils.py`. Forgetting this creates an authentication bypass.

### WebSocket vs Polling Duality

Every socket feature must work in **both** WebSocket and polling modes. The CI tests both (`funcitonal-test` and `funcitonal-test-polling` jobs). If you add WebSocket message handling, verify it also works via the `*Wrap` polling handlers.

## Security Considerations

### XSS via `TextPane`

`TextPane.js` renders user content using `innerHTML`. Any HTML/JS sent via `vis.text()` is rendered directly in the browser. This is **by design** (users need to embed rich HTML), but:
- Never expose a Visdom server to untrusted networks without authentication (`-enable_login`)
- Be cautious when accepting text content from external sources

### Path Traversal in Environment Names

Environment names are used to construct filesystem paths (`{env_path}/{eid}.json`). The `escape_eid()` function only replaces `/` with `_`. When adding new file operations:
- Always sanitize environment IDs
- Never construct paths from raw user input without validation
- Use `os.path.join()` and verify the result is within `env_path`

### Cookie Security

- Passwords are **double SHA256-hashed**: `hash_password(hash_password(password))`
- Cookie secret is stored in plaintext at `~/.visdom/COOKIE_SECRET`
- SJCL handles client-side hashing in the browser login form
- Never log or expose password hashes or cookie secrets

### Read-Only Mode

When `-readonly` is set, the `self.readonly` flag on `Application` propagates to socket handlers. The `AnySocketHandlerOrWrapper.on_message()` method returns early if `self.readonly`. Ensure any new write operations respect this flag.

## State Management Internals

### Server State (`py/visdom/server/app.py`)

The `Application` object holds all server state:

```
app.state     = {env_id: {"jsons": {win_id: window_dict}, "reload": {...}}}
app.subs      = {session_id: SocketHandler}     # read-only browser connections
app.sources   = {session_id: VisSocketHandler}  # write-enabled Python client connections
app.layouts   = "JSON string"                   # serialized view layouts
```

- **`state[eid]["jsons"]`** — Dict of window ID → window data (the actual visualization content)
- **`state[eid]["reload"]`** — Dict of window ID → layout position (restored on page reload)
- **`LazyEnvData`** — Wraps `state[eid]` to defer JSON parsing until first access. Implements `Mapping` but also supports `__setitem__`. When modifying state, always access through the dict interface, never check `isinstance(state[eid], LazyEnvData)` unless serializing.

### Frontend State (`js/main.js`)

```
storeData.panes   = {pane_id: pane_object}   # all visible panes
storeData.layout  = [{i, x, y, w, h, ...}]  # ReactGridLayout items
storeMeta.envList = [env_id, ...]            # available environments
storeMeta.layoutLists = Map(env → Map(view → Map(paneID → position)))
```

Pane updates are **batched** via `addPaneBatched()` → `processBatchedPanes()` using a 100ms `setTimeout`. This prevents re-renders for each individual window when loading environments with many panes.

### Message Flow for a New Window

```
1. Python: vis.text("hello")
2. Client: POST /events  →  {data: [{type: "text", content: "hello"}], eid: "main"}
3. Server: PostHandler.post()  →  window(req)  →  register_window(self, p, eid)
4. Server: broadcast(self, p, eid)  →  sends window dict to all matching subs
5. Browser: handleMessage(evt)  →  case "window"  →  addPaneBatched(cmd)
6. Browser: processBatchedPanes()  →  processPane()  →  setStoreData()  →  re-render
```

## Step-by-Step Recipes

### Adding a New Pane Type

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
   - Import and register in `js/settings.js` under the `PANES` dict

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

### Adding a New API Endpoint

1. **Handler** (`py/visdom/server/handlers/web_handlers.py`):
   - Create a new handler class extending `BaseHandler`
   - Implement `initialize(self, app)` copying required app attributes
   - Implement `post()` with `@check_auth` decorator
   - Use the `wrap_func` static method pattern if the endpoint needs polling support

2. **Route** (`py/visdom/server/app.py`):
   - Add the route to the `handlers` list in `Application.__init__()` (lines 97–116)
   - Use the pattern: `(r"%s/my_endpoint" % self.base_url, MyHandler, {"app": self})`
   - Place it **before** the catch-all `IndexHandler` route (must be last)

3. **Client** (`py/visdom/__init__.py`):
   - Add a method calling `self._send(msg, endpoint="my_endpoint")`

### Adding a New WebSocket Command

1. **Socket handler** (`py/visdom/server/handlers/socket_handlers.py`):
   - Add `elif cmd == "my_command":` in `AnySocketHandlerOrWrapper.on_message()`
   - Use `broadcast()` to push updates to subscribers
   - Use `send_to_sources()` to push events to Python clients

2. **Frontend** (`js/api/ApiProvider.js`):
   - Add a `sendMyCommand` function that calls `sendSocketMessage({cmd: 'my_command', ...})`
   - Export it via the `ApiContext.Provider` value

3. **Message handling** (`js/api/ApiProvider.js`):
   - Add a `case 'my_response':` in `handleMessage()` switch statement

## Known Technical Debt

Agents should be aware of these documented TODOs and architectural issues:

| Location | Issue | Impact |
|----------|-------|--------|
| `web_handlers.py:53-58` | Handler init logic should be abstracted; env/layout parsing should move to data_model | All handlers duplicate initialization code |
| `web_handlers.py:127` | `jsonpatch.make_patch` is not high-performance | Update operations may be slow for large windows |
| `web_handlers.py:139` | Embeddings updates bypass the regular update flow | Embeddings are expensive to update |
| `socket_handlers.py:44` | Client-server and visdom-server socket edges need standardization | Duplicate message handling logic |
| `base_handlers.py:80` | No `error.html` template exists | Debug errors may not render properly |
| `main.js:553,568` | Direct state mutation bypasses React | Non-conventional but intentional for relayout perf |
| `ApiProvider.js:117` | Typo: `cmd.commmand` (triple 'm') in window_update detection | May cause subtle bugs (present since original code) |
| `__init__.py:49` | Python 2 assertion still present | Could be removed (Python >= 3.8 is required) |
| `__init__.py:767-769` | `raise_exceptions` deprecation warning references July 2018 | Stale warning, never updated |

## Debugging Tips

### Server-Side

- **Increase logging**: `visdom -logging_level DEBUG` shows all WebSocket messages and handler activity
- **Inspect state**: The `DataHandler` at `/win_data` can dump raw window JSON for any environment
- **Clean state**: Use `visdom -env_path /tmp` to start with empty environments (no interference from saved data)
- **Port conflicts**: Default port 8097 may conflict; use `-port <PORT>` to change

### Frontend

- **WebSocket messages**: Open browser DevTools → Network → WS tab to inspect real-time messages between browser and server
- **React DevTools**: `react-devtools` is in `package.json` dependencies for development inspection
- **Source maps**: `webpack.dev.js` generates source maps; use `npm run dev` for debuggable builds
- **Plotly**: `Plotly` is a global — access it in the browser console to inspect chart state

### Common Error States

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Blue screen, no visualizations | CDN dependencies failed to download | Check `py/visdom/static/` for missing files; re-run `download_scripts()` or `visdom` to re-download |
| "Socket refused connection, running socketless" | Server not running or wrong port | Start server, check port matches client config |
| `win does not exist` on update | Window was closed or env was cleared | Check `vis.win_exists()` before updating |
| Panes appear but layout is broken | `localStorage` has stale layout data | Clear browser localStorage or use a fresh env |
| Visual regression test failures | Pixel differences from font rendering or timing | Compare screenshots manually; may need `test:init` re-baseline |
| `@generated` lint errors | Accidentally modified compiled files | Discard changes to `py/visdom/static/`; let CI rebuild |

## Commits and PRs

Write commit messages focused on user impact, not implementation details.

- **Good:** `Fix scatter plot not rendering with WebGL enabled`
- **Good:** `Add dual-axis line plot support`
- **Bad:** `Update __init__.py to handle edge case`

### Pull Request Checklist

1. Fork the repo and create your branch from `master`.
2. If you've added code that should be tested, add Cypress tests.
3. If you've changed APIs, update the README documentation.
4. If you've changed Python interfaces, update the type stubs in `__init__.pyi`.
5. If you change `js/`, let the GitHub Action compile static JS. **Do not** manually edit or commit files in `py/visdom/static/`.
6. Add demos in `example/components/` for new features and ensure `demo.py` still runs cleanly.
7. Lint your code:
   - JavaScript: `npm run lint`
   - Python: `black py`
8. Update the version in `py/visdom/VERSION` per [Semantic Versioning](https://semver.org/).
9. Fill in the PR template (`PULL_REQUEST_TEMPLATE.md`):
   - Description of changes
   - Motivation and context (link issues if applicable)
   - How it was tested (demo.py, Cypress, manual verification)
   - Screenshots if UI changes
   - Type of change (bug fix, new feature, breaking change, refactor)
   - Checklist items

### Issue Assignment Policy

The project does not assign issues to external contributors. Comment that you're working on it (after checking no one else is), then submit a PR.

## Boundaries

### Ask first

- Changes to the server API endpoints or message protocol.
- New Python dependencies (affects `setup.py` install requirements).
- New Node.js dependencies (affects frontend bundle size).
- Changes to environment persistence format or JSON structure.
- Modifications to authentication or cookie security.
- Large cross-component refactors (client + server + frontend).
- Changes to `setup.py` entry points or package structure.

### Never

- Commit secrets, credentials, tokens, or `COOKIE_SECRET` files.
- Manually edit generated files in `py/visdom/static/` — these are built by webpack and downloaded by `build.py`.
- Edit legacy Lua/Torch code in `th/` — deprecated since v0.1.8.4.
- Use destructive git operations (`--force`, `reset --hard`) unless explicitly requested.
- Break backward compatibility of the Python client API without discussion.
- Skip pre-commit hooks (`--no-verify`) without explicit approval.
- Push directly to `master` — use feature branches and pull requests.
- Manually edit `download.sh` — it's a legacy script, superseded by `py/visdom/server/build.py`.

## Key Dependencies

### Python (runtime — defined in setup.py)

| Package | Version | Purpose |
|---------|---------|---------|
| `numpy` | >= 1.8 | Array/tensor handling for all visualization data |
| `scipy` | any | Audio waveform → WAV conversion |
| `tornado` | any | Async web server framework |
| `requests` | any | HTTP client for Python → server communication |
| `pillow` / `pillow-simd` | any | Image processing, encoding (auto-detects simd variant) |
| `websocket-client` | any | WebSocket client for event callbacks |
| `jsonpatch` | any | JSON Patch (RFC 6902) for efficient window updates |
| `networkx` | any | Graph data structures for `vis.graph()` |
| `six` | any | Python 2/3 compatibility (legacy, used minimally) |

### Python (optional)

| Package | Purpose |
|---------|---------|
| `torch` | PyTorch tensor support (auto-converted via `@pytorch_wrap`) |
| `plotly` | Native Plotly Figure support (`vis.plotlyplot()`) |
| `beautifulsoup4` + `lxml` | Resizable matplotlib plots (`vis.matplot(resizable=True)`) |
| `av` | Video encoding from tensor input (`vis.video(tensor=...)`) |
| `matplotlib` | Matplotlib integration (`vis.matplot()`) |
| `bhtsne` | Barnes-Hut t-SNE for embeddings (install into `py/visdom/extra_deps/bhtsne/`) |

### JavaScript (frontend — defined in package.json)

| Package | Version | Purpose |
|---------|---------|---------|
| `react` / `react-dom` | 17.0.2 | UI framework (functional components + hooks) |
| `react-grid-layout` | 0.16.6 | Draggable/resizable window grid |
| Plotly.js | 2.11.1 (CDN) | Chart rendering — NOT bundled, downloaded to static/ |
| `three` | 0.105.2 | 3D mesh/surface rendering |
| `d3-selection/drag/zoom/polygon/dispatch` | 1.x | Interactions, force layout, lasso selection |
| `fast-json-patch` | 3.1.1 | JSON Patch operations for efficient data updates |
| `ml-savitzky-golay-generalized` | 4.0.1 | Line plot smoothing filter |
| `rc-tree-select` | 1.12.13 | Environment selector tree dropdown |
| `react-modal` | 3.16.1 | Modal dialogs (env management, view management) |
| `react-resize-detector` | 7.1.2 | Pane resize detection for responsive rendering |
| `jquery` | 3.6.3 | DOM manipulation, AJAX (used in ApiProvider) |
| `debounce` | 1.2.1 | Input debouncing |

### JavaScript (dev dependencies)

| Package | Purpose |
|---------|---------|
| `webpack` / `webpack-cli` | 5.x / 4.x — Module bundler |
| `babel-loader` + presets | Transpilation (ES6+, JSX → browser-compatible JS) |
| `eslint` + plugins | Code quality (React, a11y, Prettier, import sorting) |
| `prettier` | Code formatting |
| `cypress` | 9.7.0 — End-to-end testing |
| `pixelmatch` / `pngjs` | Visual regression screenshot comparison |

### External CDN Dependencies (downloaded by build.py)

Downloaded on first server run to `py/visdom/static/`:
- Plotly.js 2.11.1, jQuery 3.1.1, Bootstrap 3.3.7 (JS + CSS + fonts)
- React 16.2.0 (production), React-DOM 16.2.0, React-Modal 3.1.10
- MathJax 2.7.5 (TeX-AMS-MML_HTMLorMML config)
- D3 v3, SJCL (crypto for password hashing), layout-bin-packer
- saveSvgAsPng (SVG → PNG export), classnames
- react-resizable CSS, react-grid-layout CSS

> **Note:** The bundled React (in `static/`) is 16.2.0 for runtime, while the webpack-compiled `main.js` is built with React 17.0.2 from `node_modules`. Both are loaded in the browser. This is a known legacy setup.

## Dependency Management

### Automated Updates (Dependabot)

Dependabot is configured in `.github/dependabot.yml` to automatically open PRs for:

| Ecosystem | Frequency | Groups |
|-----------|-----------|--------|
| `npm` (package.json) | Daily | Minor + patch batched together |
| `pip` (setup.py, test-requirements.txt) | Daily | Minor + patch batched together |
| `github-actions` (workflows) | Daily | Individual PRs |

Major version bumps get individual PRs for careful review of breaking changes.

### Adding a New Dependency

**Python** — Add to `requirements` list in `setup.py` (line 40). Consider:
- Is it truly necessary? Visdom keeps dependencies minimal.
- Does it work on Python >= 3.8?
- Is `pillow-simd` auto-detection affected? (line 50)

**JavaScript** — Use `yarn add <pkg>` (updates `package.json` + `yarn.lock`). Consider:
- Does it increase the Webpack bundle size significantly?
- Is it tree-shakeable?
- CDN-loaded deps (Plotly, jQuery, Bootstrap) are **not** in `package.json` — they're downloaded by `build.py`

**CDN dependencies** — Managed in `py/visdom/server/build.py`. Adding new CDN deps requires updating `download_scripts()` and the corresponding `<script>` tags in the HTML template.

### Version Pinning Philosophy

- Python runtime deps: loosely pinned (`numpy>=1.8`, `tornado` with no pin)
- Python dev/test deps: loosely pinned in `test-requirements.txt`
- JS deps: caret ranges (`^17.0.2`) allowing minor/patch updates
- Pre-commit hooks: pinned to specific versions (Black `22.10.0`, Prettier `v2.6.2`)
- CI: Node 16, Python 3.8/3.9/3.10 matrix

## References

- [`README.md`](README.md) — Full documentation, API reference, plot options, and usage guide
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Contribution guidelines, common issue troubleshooting, UI contribution workflow
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — Contributor Covenant v1.4 (contact: opensource-conduct@fb.com)
- [`PULL_REQUEST_TEMPLATE.md`](PULL_REQUEST_TEMPLATE.md) — PR template with description, motivation, testing, and checklist
- [`LICENSE`](LICENSE) — Apache 2.0
- [`AUTHORS`](AUTHORS) — Significant contributors
- [`example/demo.py`](example/demo.py) — Full feature demo and regression baseline
- [`example/mnist-embeddings.py`](example/mnist-embeddings.py) — t-SNE embeddings example
- [Plotly.js Reference](https://plot.ly/javascript/reference/) — Chart customization options for `layoutopts` and `traceopts`
- [Plotly Python Guide](https://plot.ly/python/) — Understanding data structures for `vis._send()`
