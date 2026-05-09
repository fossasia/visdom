# Backend Context

## Python Package Structure (`py/visdom/`)

| Path | Purpose |
|------|---------|
| `__init__.py` | Visdom client class (2,594 lines, 40+ visualization methods) |
| `__init__.pyi` | Type stubs (PEP 484) for the client API |
| `py.typed` | PEP 561 marker |
| `VERSION` | Version string ("0.2.4") |
| `server/app.py` | Application class: routes, state management, user settings |
| `server/run_server.py` | CLI entry point: arg parsing, auth setup |
| `server/build.py` | `download_scripts()`: fetches CDN dependencies |
| `server/defaults.py` | DEFAULT_PORT=8097, DEFAULT_ENV_PATH |
| `server/handlers/base_handlers.py` | BaseHandler, BaseWebSocketHandler |
| `server/handlers/web_handlers.py` | HTTP request handlers (Post, Update, Close, Env, etc.) |
| `server/handlers/socket_handlers.py` | WebSocket handlers (read-only + write-enabled) |
| `utils/shared_utils.py` | warn_once, get_rand_id, ensure_dir_exists |
| `utils/server_utils.py` | check_auth, serialize_env, LazyEnvData, broadcast |

## Coding Standards

- Follow **PEP 8**. Format with **Black** (v23.1.0). CI enforces this.
- **80 character** line length.
- Python **>= 3.8** compatibility.
- All `Visdom` methods use `@pytorch_wrap` decorator for PyTorch tensor auto-conversion.
- Use `warnings.warn()` via `warn_once()` for deprecation warnings.
- Use `requests.Session` for HTTP connections (lazily created).

### License Headers

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

## Server CLI Arguments

| Flag | Description | Default |
|------|-------------|---------|
| `-port` | Server port | `8097` |
| `--hostname` | Server hostname | `localhost` |
| `-base_url` | Base URL prefix | `/` |
| `-env_path` | Environment state directory | `~/.visdom/` |
| `-logging_level` | Logging level | `INFO` |
| `-readonly` | Read-only mode | `false` |
| `-enable_login` | Require authentication | `false` |
| `-force_new_cookie` | Reset session cookie | `false` |
| `-bind_local` | Localhost only | `false` |
| `-eager_data_loading` | Pre-load all envs | `false` |
| `-use_frontend_client_polling` | HTTP polling instead of WebSockets | `false` |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `VISDOM_USE_ENV_CREDENTIALS` | Set to `1` for env-based auth |
| `VISDOM_USERNAME` | Username (when env credentials enabled) |
| `VISDOM_PASSWORD` | Password (when env credentials enabled) |
| `VISDOM_COOKIE` | Cookie secret fallback |
| `HOSTNAME` | Override hostname in startup output |

## Python Client API

**Connection & State:**
`check_connection()`, `save()`, `close()`, `delete_env()`, `fork_env()`, `get_env_list()`, `win_exists()`, `get_window_data()`, `set_window_data()`, `replay_log()`, `update_window_opts()`

**Event Handling:**
`register_event_handler()`, `clear_event_handlers()`

**Visualizations:**
`text()`, `image()`, `images()`, `audio()`, `video()`, `svg()`, `matplot()`, `plotlyplot()`, `properties()`, `embeddings()`

**Plotting:**
`scatter()`, `line()`, `bar()`, `histogram()`, `heatmap()`, `boxplot()`, `surf()`, `contour()`, `quiver()`, `stem()`, `mesh()`, `pie()`, `sunburst()`, `dual_axis_lines()`, `graph()`

## Python Dependencies

### Runtime (setup.py)

| Package | Version | Purpose |
|---------|---------|---------|
| `numpy` | >= 1.8 | Array/tensor handling |
| `scipy` | any | Audio waveform conversion |
| `tornado` | any | Async web server |
| `requests` | any | HTTP client |
| `pillow` | any | Image processing |
| `websocket-client` | any | WebSocket client |
| `jsonpatch` | any | JSON Patch for updates |
| `networkx` | any | Graph data structures |

### Optional

| Package | Purpose |
|---------|---------|
| `torch` | PyTorch tensor support |
| `plotly` | Native Plotly Figure support |
| `beautifulsoup4` + `lxml` | Resizable matplotlib plots |
| `av` | Video encoding from tensors |
| `matplotlib` | Matplotlib integration |

## Dependency Management

- Dependabot configured for npm, pip, and github-actions (daily)
- Python runtime deps: loosely pinned
- JS deps: caret ranges
- Pre-commit hooks: pinned versions
- Version stored in `py/visdom/VERSION` — changing on master triggers PyPI publish
