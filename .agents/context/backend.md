# Backend Instructions

## Key Files

- `py/visdom/__init__.py` — Client class (40+ viz methods). Use `@pytorch_wrap` on all new methods.
- `py/visdom/__init__.pyi` — Type stubs. Update when changing client API.
- `py/visdom/VERSION` — Version string. Changing on master triggers PyPI publish.
- `py/visdom/server/app.py` — Application class, routes, state management.
- `py/visdom/server/handlers/web_handlers.py` — HTTP handlers. Copy app attributes in `initialize()`, use `@check_auth`.
- `py/visdom/server/handlers/socket_handlers.py` — WebSocket handlers (read-only + write-enabled).
- `py/visdom/utils/server_utils.py` — `check_auth`, `broadcast`, `LazyEnvData`, `serialize_env`.
- `py/visdom/server/build.py` — `download_scripts()`: fetches CDN dependencies.

## Coding Rules

- Follow PEP 8, format with `black py` (v23.1.0), 80-char lines
- Python >= 3.8 compatibility
- Use `@pytorch_wrap` on all `Visdom` methods
- Use `warn_once()` for deprecation warnings

## License Headers

Add to all new files:

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

## Server Flags

`-port` (8097), `--hostname`, `-base_url`, `-env_path` (~/.visdom/), `-logging_level`, `-readonly`, `-enable_login`, `-force_new_cookie`, `-bind_local`, `-eager_data_loading`, `-use_frontend_client_polling`.

## Auth via Environment

Set `VISDOM_USE_ENV_CREDENTIALS=1` with `VISDOM_USERNAME` and `VISDOM_PASSWORD`.

## Client API

POST data with `self._send(msg)`. Update with `update` param (`'append'`, `'replace'`, `'remove'`). Register callbacks with `register_event_handler()`.

Methods: `text()`, `image()`, `images()`, `audio()`, `video()`, `svg()`, `matplot()`, `plotlyplot()`, `properties()`, `embeddings()`, `scatter()`, `line()`, `bar()`, `histogram()`, `heatmap()`, `boxplot()`, `surf()`, `contour()`, `quiver()`, `stem()`, `mesh()`, `pie()`, `sunburst()`, `dual_axis_lines()`, `graph()`.

## Dependencies

Runtime: numpy >= 1.8, scipy, tornado, requests, pillow, websocket-client, jsonpatch, networkx.
Optional: torch, plotly, beautifulsoup4 + lxml, av, matplotlib.

Ask before adding new dependencies. Dependabot handles daily updates.
