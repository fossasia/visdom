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
| `state_manager.py` | `StateManager` class wrapping the top-level `state` dict. Methods: `get_env()`, `create_env()`, `delete_env()`, `list_envs()`, `fork_env()`, `serialize()`, `serialize_all()`. Absorbs functions from `server_utils.py` (`load_env`, `gather_envs`, `compare_envs`). Environment file serialization now lives in `data_model/json_store.py` (`JSONStore`) via the `DataStore` abstraction |
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

## Phase 4: Async I/O Modernization — **delivered**
**Effort: Medium-Large | Risk: Medium | PRs: 11 | Dependencies: none in the end**

Tracked as [issue #771](https://github.com/fossasia/visdom/issues/771). The
phase was planned to wait on Phase 3, on the assumption that the file I/O had to
be concentrated in a `StateManager` before it could be moved off the loop. It
did not: `ServerState` (`py/visdom/server/server_state.py`) plus the `DataStore`
abstraction already gave every disk touch a single owner, so the async work went
ahead of the data model rather than behind it. Phase 3 is still open, and the
handlers it will rewrite are now `async def` — that changes where it lands, not
whether it can.

| Landed | What |
|--------|------|
| [#1703](https://github.com/fossasia/visdom/pull/1703) | Storage executor + off-loop save/load helpers; `check_auth` returns the wrapped result |
| [#1711](https://github.com/fossasia/visdom/pull/1711) | `/events`, `/update`, `/win_exists`, `/close`, `/win_data` off the loop |
| [#1713](https://github.com/fossasia/visdom/pull/1713) | Environment routes off the loop; PBKDF2 login off the loop |
| [#1717](https://github.com/fossasia/visdom/pull/1717) | Experiment and compare routes off the loop |
| [#1721](https://github.com/fossasia/visdom/pull/1721) | Socket commands off the loop (`async def on_message`) |
| [#1780](https://github.com/fossasia/visdom/pull/1780) | `asyncio.run` startup, graceful stop, `layout_create` on create-on-append |
| [#1784](https://github.com/fossasia/visdom/pull/1784) | `visdom.async_client.AsyncVisdom` — bridged async client |
| [#1794](https://github.com/fossasia/visdom/pull/1794) | `use_preflight_checks`: one POST per append instead of two |
| [#1800](https://github.com/fossasia/visdom/pull/1800) | Async backchannel — websocket and polling |
| [#1808](https://github.com/fossasia/visdom/pull/1808) | `async_client.pyi`, and `__init__.pyi` brought back in step |
| [#1816](https://github.com/fossasia/visdom/pull/1816) | README + website docs, `example/async_demo.py` |

### 4a. Blocking file I/O — where it went

Every row of the original table now runs on the storage worker, reached through
`run_on_storage_executor` in `server_utils.py`:

| Was blocking | Now |
|--------------|-----|
| `JSONStore.save_envs()` / `save_env()` | `save_env_off_loop`, `save_envs_off_loop`, `save_all_off_loop` |
| `compare_envs()` env reads | `CompareHandler` awaits the comparison on the worker |
| Experiment search's full-disk scan | `ensure_env_loaded` per eid, then the unchanged sync search over warm state |
| Layout save / load (`app.py`) | `ServerState.save_layouts`, awaited off the loop |
| State load at startup | `ServerState`, before the loop starts serving |
| PBKDF2 login hash (~50-100 ms) | The **default** executor, not the storage one — logins must not queue behind env saves |

CSS reads at import time are the deliberate exception: they happen once, before
the server accepts a connection.

### 4b. Handlers

The handler entrypoints that touch storage are `async def` (`get`, `post`,
`on_message`); the ones that only read memory or serve a static asset were left
synchronous. The `wrap_func` staticmethods stayed synchronous too — they are
pure state manipulation, and keeping them sync is what let the polling bridge
and the websocket path share one body.

Two endpoints do not hold that line yet; see follow-up 4j.

`check_auth` was the blocker, and its fix is the reason no handler needed a
per-handler edit: it discarded the wrapped call's return value, so an
`async def post` under it produced a coroutine that nothing awaited and a silent
empty 200. It now returns the result untouched and carries `functools.wraps`.

### Invariants a later change can break silently

1. **Disk work belongs to one worker.** `ServerState.storage_executor` is
   `ThreadPoolExecutor(max_workers=1)`. The single worker is what serializes
   writes: with two, two saves of the same env interleave and leave a
   half-written file. Widening it is a data-loss change, not a tuning knob.
2. **Snapshot on the loop, hand the copy to the worker.** `snapshot_env` /
   `snapshot_envs` deep-copy on the IOLoop thread before the executor call.
   Passing live state to a worker means the loop can mutate an env mid-write.
   This also fixes the two pre-existing fire-and-forget `run_in_executor` races
   in `socket_handlers.py`.
3. **Re-check identity after every await.** An env can be deleted while a read
   of it is parked. `ServerState.deleting_envs` exists so a resumed read does
   not file what it read back into `state` and resurrect a deleted env.
4. **Shutdown order is: stop autosave, drain the executor, then save.** See
   `ServerState.shutdown_storage`. Draining after the final save lets a queued
   write land on top of it and put stale state back on disk. The method is
   idempotent because both the graceful stop and the `atexit` fallback call it.

### 4c / 4d — legacy shims and string formatting

Done in passing over the phase; the `collections.abc` fallbacks, the Python 2
assertion and the PyTorch < 0.4 warnings are gone. The Lua Torch notice in
`web_handlers.py` stays: it is a live error message for old clients, not a shim.

### The async client is a bridge, not a second client

`py/visdom/async_client.py` adds `AsyncVisdom` without duplicating any of the
40+ plotting methods. `_BridgedVisdom` subclasses `Visdom` and overrides not one
of them: the substantive override is `_handle_post`, the documented transport
seam, which hands the request to the caller's loop with
`asyncio.run_coroutine_threadsafe`. (`_start_session_reaper` and `setup_socket`
are overridden too, as lifecycle stubs — the loop owns both.) Method bodies run
on a worker thread; only the wire hop is async.

That shape is forced by the client, not chosen for convenience: `scatter` and
`image` need the result of a mid-method `win_exists` synchronously, and a
synchronous body cannot await. Rewriting those bodies as coroutines would have
meant maintaining two copies of every plotting method. As a side effect the
CPU-heavy encodes (PNG/base64, `savefig`, t-SNE) also land off the loop.

Two details are load-bearing:

- **The client owns its thread pool.** Not `asyncio.to_thread`: asyncio resolves
  hostnames on the default executor, so plot calls parked there waiting on their
  POST starve the `getaddrinfo` those same POSTs need, and a `gather` wider than
  the default pool deadlocks until every request hits its connect timeout.
- **`create()` flips two defaults.** `use_incoming_socket` and
  `use_preflight_checks` both default to `False` on `AsyncVisdom` and stay
  `True` on `Visdom`. The synchronous client's wire traffic is unchanged
  byte-for-byte; opting in is a caller's decision.

`AsyncVisdom` proxies 62 names through `__getattr__` against an explicit
`_PROXIED` allowlist. Because the methods are manufactured, neither an import
nor a type check catches a typo or a missing `await` — `py/tests/unit/async_docs.py`
and `py/tests/unit/client_stubs.py` are what do.

### Benchmarks (loopback, `line(update='append')` x 300)

The numbers issue #771 asked for. Also quoted in the README and on the website
page, and cross-checked by `py/tests/unit/async_docs.py`.

| Client | plots/s | p50 | p95 |
|---|---|---|---|
| `Visdom`, preflight on (unchanged default) | 198 | 5.00 ms | 5.73 ms |
| `Visdom`, `use_preflight_checks=False` | **304** | 3.32 ms | 4.09 ms |
| `AsyncVisdom`, awaited serially | 235 | 4.24 ms | 4.87 ms |
| `AsyncVisdom`, 8 concurrent | **410** | 13.19 ms | 18.33 ms |

Requests halve exactly — 12 POSTs become 6 over a mixed append/image-history
script, and 6 `/win_exists` become 0 — and the resulting server state is
byte-identical between the two preflight modes. Throughput is +53% rather than
+100% because on loopback the preflight is the cheaper of the two round trips;
over a real network the two cost the same and the ratio approaches 2x.

### Follow-ups not taken

| # | Item | Why it was left |
|---|------|-----------------|
| 4e | Bound the storage queue | An unbounded backlog of queued saves is memory the server cannot reclaim. Needs a policy for what to drop, which is a product decision |
| 4f | Per-env write locks instead of one global worker | Would let independent envs save in parallel. Only worth it once a profile shows the single worker is the bottleneck; today it is not |
| 4g | `AsyncVisdom` HTTP proxy support | `create()` raises `NotImplementedError` for `proxies` / `http_proxy_host`: tornado's `AsyncHTTPClient` has no proxy support without pycurl, which would be a new dependency |
| 4h | Native async plotting bodies | Only worth doing if the bridge's thread pool ever shows up in a profile. It would fork every plotting method, so the bar is high |
| 4i | Retire the polling backchannel | Both clients carry a websocket path and an HTTP polling fallback, and every socket change has to be made twice. Phase 6 is where that gets decided |
| 4j | `/experiments/hparams` and `/experiments/hparams/update` still write on the loop | Both handlers are synchronous and their `wrap_func` calls `handler.storage.save_env` inline, and the selection they build reads through `ExperimentStore` on the loop. They arrived with the hparams track after this phase's server PRs were scoped, so nothing converted them. Small and mechanical — `async def post` plus `save_env_off_loop` — but it is a live write path and belongs in its own PR. `py/tests/unit/refactoring_docs.py` records both sites, so a third one fails the suite |

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
| [#771](https://github.com/fossasia/visdom/issues/771) (client 10x slower than the caller's script) | Phase 4 | **Delivered** — preflight removed, `AsyncVisdom` added; numbers above |
| [#989](https://github.com/fossasia/visdom/issues/989) (async race condition in env switching) | Phases 3 + 4 | Partly addressed — Phase 4 put the snapshot-before-offload and `deleting_envs` guards in place. The switching race itself still wants StateManager |
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
| `__init__.py` — removed legacy send bypass | Phase 5 |
| `server_utils.py:56` — shared method call | Phase 2 |
| `base_handlers.py:80` — error.html page | Phase 2 |
| `socket_handlers.py:238` — message format | Phase 6 |

---

## Execution Order & Parallelism

```
Phase 1 (bugs) ──────────────────────────→ Phase 5 (client split) ──→
Phase 2 (dedup) ──→ Phase 3 (data model) ──────────────────────────→ Phase 6 (protocol)
Phase 4 (async) ✔ done, ahead of Phase 3
```

Phases 1 & 2 can start immediately in parallel. Phase 5 can proceed independently after Phase 1.

Phase 4 was planned as a dependant of Phase 3 and did not turn out to be one — the
disk I/O already had a single owner. Phase 6 keeps its Phase 3 dependency, and it
inherits one thing from Phase 4: the protocol it standardizes is now spoken by two
clients, `Visdom` and `AsyncVisdom`, over two transports each.

**Estimated total: 10-13 PRs across the remaining phases; Phase 4 took 13 of its own.**

---

## Verification Plan

For each phase:
1. Run existing tests: `python -m pytest` (config in `pyproject.toml`; suite lives in `py/tests/`).
   Every new file needs `pytestmark = pytest.mark.unit` or `pytest.mark.integration` —
   CI runs the two as separate jobs, so an unmarked file runs in neither
2. Run Playwright E2E: `npm test` and `npm run test:polling`
3. Manual smoke test: `python -m visdom.server -port 8098` then run `example/demo.py`
4. Verify no regressions in visual regression screenshots
5. Run linting: `black py` and `npm run lint`

---

## Critical Files Reference

| File | Lines | Touched By |
|------|-------|------------|
| `py/visdom/__init__.py` | 4,974 | Phases 1, 5 |
| `py/visdom/async_client.py` | 940 | Phase 4 (new) |
| `py/visdom/server/server_state.py` | 398 | Phase 4 (new); future home for Phase 3 |
| `py/visdom/server/handlers/web_handlers.py` | 1,602 | Phases 2, 3, 4 |
| `py/visdom/server/handlers/socket_handlers.py` | 908 | Phases 2, 3, 4, 6 |
| `py/visdom/server/handlers/base_handlers.py` | 149 | Phase 2 |
| `py/visdom/utils/server_utils.py` | 1,081 | Phases 2, 3, 4 |
| `py/visdom/server/app.py` | 381 | Phases 3, 4 |
| `py/visdom/server/run_server.py` | 486 | Phase 4 |
| `py/visdom/utils/shared_utils.py` | 219 | Phase 1 |

Line counts drift; they are here for relative size, not as an assertion.
