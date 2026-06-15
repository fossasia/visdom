# Visdom Server Refactoring — Continuation Roadmap

> **Reference:** [PR #675 - Server Refactor](https://github.com/fossasia/visdom/pull/675) by Jack Urbanek

## Context

PR #675 completed the **structural split** of the monolithic `server.py` (~2,000 lines) into modular files under `py/visdom/server/` and `py/visdom/utils/`. That work is merged and done.

However, the PR explicitly outlined follow-up work in TODO comments (`socket_handlers.py:41-48`, `web_handlers.py:54-59`) that was **never completed**. The maintainer wants this remaining work picked up. This plan covers everything that's left, prioritized by impact and risk.

### Current Modular Structure (from PR #675)

```
py/visdom/
├── server/
│   ├── __main__.py          (Entry point)
│   ├── app.py               (Application orchestration)
│   ├── build.py             (Asset management)
│   ├── defaults.py          (Configuration)
│   ├── run_server.py        (Server startup)
│   └── handlers/
│       ├── base_handlers.py (Base handler classes)
│       ├── socket_handlers.py (WebSocket handlers)
│       └── web_handlers.py  (HTTP handlers)
└── utils/
    ├── server_utils.py      (Server utilities)
    └── shared_utils.py      (Shared utilities)
```

---

## Phase 1: Bug Fixes & Resource Safety
**Effort: Small | Risk: Low | PRs: 1 | Dependencies: None**

These are actual bugs and resource leaks that can cause data loss or event loop stalls in production.

| # | Issue | File | Lines | Fix |
|---|-------|------|-------|-----|
| 1a | Resource leak in `loadfile()` | `py/visdom/__init__.py` | 137-143 | File opened without context manager; if assert fires, handle leaks. Rewrite with `with open()` |
| 1b | Bare `except:` clause | `py/visdom/__init__.py` | 2647 | Catches `SystemExit`/`KeyboardInterrupt`. Change to `except ImportError:` |
| 1c | Thread lifecycle bug | `py/visdom/__init__.py` | 648-651 | `setup_polling()` thread missing `daemon=True` (compare with `setup_socket()` at 729-733 which has it). Prevents clean process exit |
| 1d | Thread-unsafe global | `py/visdom/utils/shared_utils.py` | 20 | `_seen_warnings = set()` accessed from multiple threads without lock |
| 1e | Broad exception swallowing | `py/visdom/server/handlers/base_handlers.py` | 35, 57 | Narrow `except Exception` to specific exception types |

---

## Phase 2: Eliminate Code Duplication
**Effort: Small-Medium | Risk: Low | PRs: 1 | Dependencies: None (parallel with Phase 1)**

### 2a. Consolidate 13 duplicate `initialize()` methods
The same 6-line `initialize(self, app)` is copy-pasted across 13 handlers in `web_handlers.py`:
- `PostHandler` (line 61), `ExistsHandler` (line 90), `UpdateHandler` (line 115), `DeleteEnvHandler` (line 423), `EnvStateHandler` (line 471), `ForkEnvHandler` (line 491), `CompareHandler`, `DataHandler`, `SaveHandler`, etc.

**Fix:** Move into `BaseHandler` in `base_handlers.py`. Handlers needing extras (`IndexHandler` needs `user_credential`, `wrap_socket`, `base_url`) call `super().initialize(app)` then add their own.

### 2b. Deduplicate `delete_env` logic
Identical environment deletion code exists in:
- `web_handlers.py` `DeleteEnvHandler.wrap_func` (lines 432-460)
- `socket_handlers.py` `on_message` delete_env branch (lines 127-155)

**Fix:** Extract to `delete_env_files(env_path, eid)` in `server_utils.py`.

### 2c. Deduplicate `get_rand_id`
Two implementations:
- `shared_utils.py:36` — `str(uuid.uuid4())` (good)
- `__init__.py:107` — time-based hex (weak, not unique under rapid calls)

**Fix:** Use UUID version everywhere.

---

## Phase 3: Data Model Layer (Core Architecture Work)
**Effort: Large | Risk: Medium | PRs: 2-3 | Dependencies: Phase 2**

This is the primary TODO from PR #675: *"move the logic that actually parses environments and layouts to new classes in the data_model folder"*

### 3a. Create `py/visdom/server/data_model/` package

| File | Purpose |
|------|---------|
| `environment.py` | `Environment` class wrapping `{"jsons": {}, "reload": {}}` dict. Methods: `get_window()`, `set_window()`, `remove_window()`, `list_windows()`, `get_reload()` |
| `state_manager.py` | `StateManager` class wrapping the top-level `state` dict. Methods: `get_env()`, `create_env()`, `delete_env()`, `list_envs()`, `fork_env()`, `serialize()`, `serialize_all()`. Absorbs functions from `server_utils.py` (`serialize_env`, `serialize_all`, `load_env`, `gather_envs`, `compare_envs`) |
| `window.py` | Typed window structures (dataclasses/TypedDicts) replacing raw dicts built in `server_utils.py:window()` (lines 202-258) |

### 3b. Refactor handlers to use data model
- Replace `handler.state[eid]["jsons"][win]` patterns in `web_handlers.py` and `socket_handlers.py` with `state_manager.get_env(eid).get_window(win)`
- Move `register_window()` and `window()` from `server_utils.py` into data model
- Move `LazyEnvData` (server_utils.py:84-118) into `data_model/environment.py`

### Target Structure After Phase 3

```
py/visdom/server/
├── data_model/
│   ├── __init__.py
│   ├── environment.py    (Environment class + LazyEnvData)
│   ├── state_manager.py  (StateManager - centralized state ops)
│   └── window.py         (Typed window dataclasses)
├── handlers/
│   ├── base_handlers.py  (Shared initialize logic)
│   ├── socket_handlers.py (Uses StateManager, not raw dicts)
│   └── web_handlers.py   (Uses StateManager, not raw dicts)
└── ...
```

---

## Phase 4: Async I/O Modernization
**Effort: Medium-Large | Risk: Medium | PRs: 2 | Dependencies: Phase 3**

### 4a. Wrap blocking file I/O with `run_in_executor`
Currently only **ONE** place uses async I/O (`socket_handlers.py:123` for `serialize_all`). All others block the Tornado event loop:

| File | Lines | Blocking Operation |
|------|-------|-------------------|
| `server_utils.py` | 72 | Cookie file write |
| `server_utils.py` | 121-155 | `serialize_env()` — JSON file write |
| `server_utils.py` | 273-303 | `compare_envs()` — env file read |
| `app.py` | 141 | Layout save (file write) |
| `app.py` | 155 | Layout load (file read) |
| `app.py` | 183 | State load (JSON file reads) |
| `app.py` | 238, 242 | CSS file reads |

With Phase 3's `StateManager`, all file I/O concentrates in one place — easy to wrap.

### 4b. Convert handlers to `async def` / `await`
Tornado 6+ supports native coroutines. Convert all handler `get()`/`post()`/`on_message()` to `async def`. Update `check_auth` decorator in `server_utils.py:49`.

### 4c. Remove legacy compatibility shims
- `collections.abc.Sequence` fallback in 3 files (`__init__.py:19-24`, `server_utils.py:30-35`, `web_handlers.py:26-31`)
- Python 2 assert at `__init__.py:51`
- PyTorch < 0.4 deprecation warnings (`__init__.py:407-410`)
- Lua Torch deprecation notice (`web_handlers.py:76-81`)

### 4d. Standardize string formatting
Mixed `%`, `.format()`, and f-strings throughout. Standardize on f-strings.

---

## Phase 5: Client Package Split (`__init__.py`)
**Effort: Large | Risk: Medium | PRs: 3-4 | Dependencies: Phase 1 | Can parallel with Phases 3-4**

The 2,712-line `__init__.py` monolith needs splitting:

| PR | New File | Content | Lines Moved |
|----|----------|---------|-------------|
| 5a | `py/visdom/client/utils.py` | Utility functions: `get_rand_id`, `isstr`, `isnum`, `nan2none`, `loadfile`, `_axisformat`, `_opts2layout`, etc. | ~350 lines (106-450) |
| 5b | `py/visdom/client/core.py` | `Visdom` class: init, session, connection, event handlers, save/fork/close | ~520 lines (452-975) |
| 5c | `py/visdom/client/plotting.py` | All visualization methods: `text`, `image`, `scatter`, `line`, `heatmap`, `bar`, etc. | ~1,700 lines (977-2712) |
| 5d | Update `__init__.py` | Re-exports only, preserving backward compatibility | imports only |

---

## Phase 6: Socket Protocol Standardization
**Effort: Medium | Risk: Low | PRs: 2 | Dependencies: Phases 3, 4**

From TODO at `socket_handlers.py:47-48`: *"standardize the code between the client-server and visdom-server socket edges"*

### 6a. Define message protocol
Create `py/visdom/server/protocol.py` with typed message definitions (dataclasses):
- **Server->Client:** `AliveMessage`, `WindowMessage`, `WindowUpdateMessage`, `LayoutUpdateMessage`
- **Client->Server:** `CloseCommand`, `SaveCommand`, `DeleteEnvCommand`, `ForwardToVisCommand`

### 6b. Unify polling and WebSocket message formatting
The TODO at `socket_handlers.py:238` notes inconsistent message JSON formatting between paths. Ensure consistent encoding across all communication channels.

---

## Open Issues Alignment

| Issue | Related Phase | How Addressed |
|-------|---------------|---------------|
| [#989](https://github.com/fossasia/visdom/issues/989) (async race condition in env switching) | Phases 3 + 4 | StateManager with proper locking + async I/O |
| [#1324](https://github.com/fossasia/visdom/issues/1324) (refactor image rendering logic) | Phases 3 + 5 | Typed window models + plotting extraction |
| [#1310](https://github.com/fossasia/visdom/issues/1310) (multi-tenant architecture) | Phase 3 | StateManager provides isolation foundation |

---

## TODO Debt Resolved (17+ items)

| TODO Location | Phase |
|---------------|-------|
| `socket_handlers.py:41` — data model | Phase 3 |
| `socket_handlers.py:43` — base handler init | Phase 2 |
| `socket_handlers.py:45` — abstract app refs | Phase 3 |
| `socket_handlers.py:47` — standardize protocol | Phase 6 |
| `web_handlers.py:54-59` — same 4 TODOs | Phases 2, 3, 6 |
| `web_handlers.py:147` — embeddings update flow | Phase 3 |
| `web_handlers.py:166` — python client function | Phase 5 |
| `web_handlers.py:478` — env state handler | Phase 3 |
| `__init__.py:602` — merge setup_polling/setup_socket | Phase 5 |
| `__init__.py:779` — investigate/deprecate send | Phase 5 |
| `server_utils.py:56` — shared method call | Phase 2 |
| `base_handlers.py:80` — error.html page | Phase 2 |
| `socket_handlers.py:238` — message format | Phase 6 |

---

## Execution Order & Parallelism

```
Phase 1 (bugs) ──────────────────────────→ Phase 5 (client split) ──→
Phase 2 (dedup) ──→ Phase 3 (data model) ──→ Phase 4 (async) ──→ Phase 6 (protocol)
```

Phases 1 & 2 can start immediately in parallel. Phase 5 can proceed independently after Phase 1. Phases 3 -> 4 -> 6 are sequential.

**Estimated total: 10-13 PRs across all phases.**

---

## Verification Plan

For each phase:
1. Run existing tests: `cd py && python -m pytest ../test/`
2. Run Cypress E2E: `npm run test` (server on port 8098)
3. Manual smoke test: `python -m visdom.server -port 8098` then run `example/demo.py`
4. Verify no regressions in visual regression screenshots
5. Run linting: `black py` and `npm run lint`

---

## Critical Files Reference

| File | Lines | Touched By |
|------|-------|------------|
| `py/visdom/__init__.py` | 2,712 | Phases 1, 5 |
| `py/visdom/server/handlers/web_handlers.py` | 708 | Phases 2, 3, 4 |
| `py/visdom/server/handlers/socket_handlers.py` | 409 | Phases 2, 3, 4, 6 |
| `py/visdom/server/handlers/base_handlers.py` | 84 | Phase 2 |
| `py/visdom/utils/server_utils.py` | 568 | Phases 2, 3, 4 |
| `py/visdom/server/app.py` | 248 | Phases 3, 4 |
| `py/visdom/utils/shared_utils.py` | 62 | Phase 1 |
