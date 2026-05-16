# Architecture Context

## Components

1. **Python Client** (`py/visdom/__init__.py`, 2,594 lines) — The `Visdom` class provides 40+ visualization methods. Communicates with the server via HTTP POST (using `requests.Session`) and WebSocket (`websocket-client`). Supports PyTorch tensor auto-conversion via the `@pytorch_wrap` decorator. Also supports offline mode and a polling fallback.

2. **Tornado Server** (`py/visdom/server/`) — `Application` class manages:
   - `self.state` — Dict mapping environment IDs to window data (loaded via `LazyEnvData`)
   - `self.subs` — Dict of read-only WebSocket subscriber connections
   - `self.sources` — Dict of write-enabled WebSocket source connections
   - `self.layouts` — JSON string of saved view layouts
   - Authentication via Tornado's secure cookies (SHA256-hashed)

3. **React Frontend** (`js/`, compiled by Webpack 5 into `py/visdom/static/js/main.js`) — Single-page application using React 17, Plotly.js, ReactGridLayout, D3, Three.js, and MathJax.

## Data Flow

```
Python Client  ──HTTP POST /events──>  Tornado Server  ──WebSocket──>  React Frontend (Browser)
      │                                      │
      │<──WebSocket /vis_socket──────────────│  (event callbacks)
      │                                      │
      │                               JSON files (~/.visdom/)
      │                                 ├── main.json
      │                                 ├── <env>.json
      │                                 └── view/layouts.json
```

## Repository Structure

```
visdom/
├── py/visdom/                           — Python package (client + server)
│   ├── __init__.py                      — Visdom client class
│   ├── __init__.pyi                     — Type stubs (PEP 484)
│   ├── VERSION                          — Version string ("0.2.4")
│   ├── server/                          — Tornado web server
│   │   ├── app.py                       — Application class: routes, state management
│   │   ├── run_server.py                — CLI entry point
│   │   ├── build.py                     — download_scripts(): fetches CDN deps
│   │   ├── defaults.py                  — DEFAULT_PORT=8097, DEFAULT_ENV_PATH
│   │   └── handlers/                    — HTTP + WebSocket request handlers
│   └── utils/                           — Shared and server utilities
├── js/                                  — React frontend source
│   ├── main.js                          — App entry: grid layout, env management
│   ├── api/                             — WebSocket connection, message routing
│   ├── panes/                           — Visualization pane components
│   ├── topbar/                          — Top bar controls
│   └── modals/                          — Dialog components
├── cypress/                             — End-to-end + visual regression tests
├── example/                             — Demo scripts
└── .github/workflows/                   — CI/CD workflows
```

## API Endpoints

Defined in `py/visdom/server/app.py` (lines 97-116). All endpoints are prefixed with `base_url`.

| Endpoint | Handler | Purpose |
|----------|---------|---------|
| `/events` | `PostHandler` | Create new windows / send visualization data |
| `/update` | `UpdateHandler` | Update existing window data |
| `/close` | `CloseHandler` | Close a window |
| `/socket` | `SocketHandler` | Read-only WebSocket connection |
| `/vis_socket` | `VisSocketHandler` | Write-enabled WebSocket connection |
| `/env/<eid>` | `EnvHandler` | Load or create an environment |
| `/compare/<eid>` | `CompareHandler` | Compare multiple environments |
| `/save` | `SaveHandler` | Persist environment state to disk |
| `/delete_env` | `DeleteEnvHandler` | Delete an environment |
| `/fork_env` | `ForkEnvHandler` | Clone an environment |

## Window Types

| Type | Frontend Component | Description |
|------|-------------------|-------------|
| `plot` | `PlotPane.js` | All Plotly-based charts |
| `image` | `ImagePane.js` | Single image with zoom/pan |
| `image_history` | `ImagePane.js` | Image with history slider |
| `text` | `TextPane.js` | Arbitrary HTML/text content |
| `properties` | `PropertiesPane.js` | Interactive form widgets |
| `network` | `NetworkPane.js` | D3 force-directed graph |
| `embeddings` | `EmbeddingsPane.js` | t-SNE visualization with lasso |

## State Management

### Server State (`py/visdom/server/app.py`)

```
app.state     = {env_id: {"jsons": {win_id: window_dict}, "reload": {...}}}
app.subs      = {session_id: SocketHandler}
app.sources   = {session_id: VisSocketHandler}
app.layouts   = "JSON string"
```

### Frontend State (`js/main.js`)

```
storeData.panes   = {pane_id: pane_object}
storeData.layout  = [{i, x, y, w, h, ...}]
storeMeta.envList = [env_id, ...]
```

Pane updates are batched via `addPaneBatched()` → `processBatchedPanes()` using a 100ms `setTimeout`.

## Data Storage

- **Location:** `~/.visdom/` (configurable via `-env_path`)
- **Format:** JSON files per environment
- **Lazy loading:** `LazyEnvData` defers JSON parsing until first access
- **Env naming:** `/` characters escaped to `_` via `escape_eid()`

## Authentication

- Cookie-based with Tornado's `set_secure_cookie`
- Password is double SHA256-hashed
- SJCL used client-side for password hashing in the browser login form
- Cookie secret stored in `~/.visdom/COOKIE_SECRET`

## Known Technical Debt

| Location | Issue |
|----------|-------|
| `web_handlers.py:53-58` | Handler init logic should be abstracted |
| `web_handlers.py:127` | `jsonpatch.make_patch` is not high-performance |
| `socket_handlers.py:44` | Socket edges need standardization |
| `ApiProvider.js:117` | Typo: `cmd.commmand` (triple 'm') |
| `__init__.py:49` | Python 2 assertion still present |
