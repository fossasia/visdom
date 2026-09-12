# Architecture Context

## Components

1. **Python Client** (`py/visdom/__init__.py`) — The `Visdom` class provides 40+ visualization methods. Communicates with the server via HTTP POST (using `requests.Session`) and WebSocket (`websocket-client`). Supports PyTorch tensor auto-conversion via the `@pytorch_wrap` decorator. Also supports offline mode and a polling fallback.

2. **Async Python Client** (`py/visdom/async_client.py`) — `AsyncVisdom`, an awaitable front end to the same `Visdom`. It duplicates none of the plotting methods: `_BridgedVisdom` subclasses `Visdom` and overrides only `_handle_post`, so method bodies run on the client's own thread pool while the wire hop runs on the caller's event loop. Opt-in; `Visdom` is unchanged.

3. **Tornado Server** (`py/visdom/server/`) — `ServerState` (`server_state.py`) owns the server-wide containers; `Application` wires routes to them and handlers reach them through `StateAccessorsMixin`:
   - `state` — Dict mapping environment IDs to window data (loaded via `LazyEnvData`)
   - `subs` — Dict of read-only WebSocket subscriber connections
   - `sources` — Dict of write-enabled WebSocket source connections
   - `layouts` — JSON string of saved view layouts
   - `storage` / `storage_executor` — the `DataStore` backend and the single thread every disk touch goes through
   - Authentication via Tornado's secure cookies (SHA256-hashed)

4. **React Frontend** (`js/`, compiled by Webpack 5 into `py/visdom/static/js/main.js`) — Single-page application using React 17, Plotly.js, ReactGridLayout, D3, Three.js, and MathJax.

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
│   ├── async_client.py(+.pyi)           — AsyncVisdom: awaitable front end to Visdom
│   ├── VERSION                          — Version string ("0.3.0")
│   ├── data_model/                      — DataStore abstraction + JSONStore backend
│   ├── server/                          — Tornado web server
│   │   ├── app.py                       — Application class: routes, wiring
│   │   ├── server_state.py              — ServerState: containers, storage executor, autosave
│   │   ├── run_server.py                — CLI entry point, asyncio.run startup, graceful stop
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
├── playwright/                          — End-to-end + visual regression tests
├── example/                             — Demo scripts
└── .github/workflows/                   — CI/CD workflows
```

## API Endpoints

Defined in `py/visdom/server/app.py`. All endpoints are prefixed with `base_url`. Handler entrypoints are `async def`; see Concurrency Model below.

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

### Server State (`py/visdom/server/server_state.py`)

```
state     = {env_id: {"jsons": {win_id: window_dict}, "reload": {...}}}
subs      = {session_id: SocketHandler}
sources   = {session_id: VisSocketHandler}
layouts   = "JSON string"
```

Handlers read these as `self.state`, `self.subs`, … via `StateAccessorsMixin`, which
returns the `ServerState` containers. They are mutated in place, never rebound.

### Frontend State (`js/main.js`)

```
storeData.panes   = {pane_id: pane_object}
storeData.layout  = [{i, x, y, w, h, ...}]
storeMeta.envList = [env_id, ...]
```

Pane updates are batched via `addPaneBatched()` → `processBatchedPanes()` using a 100ms `setTimeout`.

## Concurrency Model

Tornado runs on asyncio and the handler entrypoints are `async def`, so anything
that blocks the IOLoop stalls every other connection. Four rules keep that from
happening; breaking one of them fails quietly rather than loudly.

1. **No disk work on the loop.** Go through `run_on_storage_executor` (or the
   `*_off_loop` helpers) in `py/visdom/utils/server_utils.py`.
2. **One storage worker.** `ServerState.storage_executor` is
   `ThreadPoolExecutor(max_workers=1)`, and the single worker is what serializes
   writes — two saves of one env would otherwise interleave and truncate a file.
   Widening it loses data.
3. **Snapshot on the loop, hand the copy to the worker.** `snapshot_env` /
   `snapshot_envs` deep-copy before the executor call, so the loop cannot mutate
   an env mid-write.
4. **Re-check identity after every `await`.** An env can be deleted while a read
   of it is parked; `ServerState.deleting_envs` records that, and a resumed read
   must not file its result back into `state`.

Password hashing (PBKDF2, ~50-100 ms) goes to the **default** executor instead, so
logins do not queue behind environment saves. Shutdown order is fixed in
`ServerState.shutdown_storage`: stop autosave, drain the executor, then save.

Full history and the follow-ups that were left: `REFACTORING.md`, Phase 4.

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
| `web_handlers.py:81` | Environment/layout parsing should move to `data_model` (Phase 3) |
| `web_handlers.py:150` | `jsonpatch.make_patch` is not high-performance |
| `socket_handlers.py:50` | Socket edges need standardization (Phase 6) |
| `py/visdom/__init__.py` | 4,974 lines; still awaiting the Phase 5 package split |
