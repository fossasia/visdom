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
| `state_manager.py` | `StateManager` class wrapping the top-level `state` dict. Methods: `get_env()`, `create_env()`, `delete_env()`, `list_envs()`, `fork_env()`, `serialize()`, `serialize_all()`. Absorbs functions from `server_utils.py` (`load_env`, `compare_envs`). Environment file serialization now lives in `data_model/json_store.py` (`JSONStore`) via the `DataStore` abstraction |
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
| Hyper-parameter pane selection + save | `_select_hparams` on the worker over a loop-side copy of the resident experiments, then `save_env_off_loop` |
| `/close`'s undo entry | `push_deleted_many_off_loop`: the panes are popped on the loop, then their undo entries are written as one task rather than one per pane |
| The login page's env listing | Removed. `login.html` has never rendered the `items` it was handed, so the directory read was built and thrown away |
| Layout save / load (`app.py`) | `ServerState.save_layouts`, awaited off the loop |
| State load at startup | `ServerState`, before the loop starts serving |
| PBKDF2 login hash (~50-100 ms) | The **default** executor, not the storage one — logins must not queue behind env saves |

CSS reads at import time are the deliberate exception: they happen once, before
the server accepts a connection.

### 4b. Handlers

The handler entrypoints that touch storage are `async def` (`post`,
`on_message`); the ones that only read memory or serve a static asset were left
synchronous — `IndexHandler.get` among them, once the env listing it never
rendered was dropped. Most `wrap_func` staticmethods stayed synchronous as well:
they are pure state manipulation, and keeping them sync is what let the polling
bridge and the websocket path share one body. The exceptions are the ones whose
own body has to reach the disk — the two hyper-parameter pane endpoints, and
`CloseHandler`, which awaits the undo entry it leaves behind.

The two hyper-parameter pane endpoints, `/experiments/hparams` and
`/experiments/hparams/update`, arrived with the hparams track after the handler
line was drawn and were brought across afterwards; see follow-up 4j. The
live-refresh queue that drives the update endpoint drains as a coroutine on the
loop, awaiting each rebuild in turn.

`check_auth` was the blocker, and its fix is the reason no handler needed a
per-handler edit: it discarded the wrapped call's return value, so an
`async def post` under it produced a coroutine that nothing awaited and a silent
empty 200. It now returns the result untouched and carries `functools.wraps`.

### Invariants a later change can break silently

1. **Disk work belongs to one worker.** `ServerState.storage_executor` is
   `ThreadPoolExecutor(max_workers=1)`. The single worker is what serializes
   writes: with two, two saves of the same env interleave and leave a
   half-written file. Widening it is a data-loss change, not a tuning knob.
   Reaching the disk through a helper counts: a `server_utils` function that
   takes a `store` is disk work wherever it is called, and calling one on the
   loop is the same stall as calling the backend there. `py/tests/unit/refactoring_docs.py`
   scans the handler modules for both shapes -- the backend called directly, and
   a store-taking helper called inline -- and the only calls it allows on the
   loop are the ones handed the answer to the read. What it checks there is the
   *value*: `warmed=True` frees the read, `warmed=False` is the default spelled
   out and still reads, so the scanner reads the argument rather than noting
   that it is present.
2. **Snapshot on the loop, hand the copy to the worker.** `snapshot_env` /
   `snapshot_envs` deep-copy on the IOLoop thread before the executor call.
   Passing live state to a worker means the loop can mutate an env mid-write.
   This also fixes the two pre-existing fire-and-forget `run_in_executor` races
   in `socket_handlers.py`.
3. **Re-check identity after every await.** An env can be deleted while a read
   of it is parked. `ServerState.deleting_envs` exists so a resumed read does
   not file what it read back into `state` and resurrect a deleted env. It is
   cleared the moment the delete lands, so it only answers for a delete the
   read overlapped; a read that outlived one is told nothing, and the readers
   that have to catch that hold a `watch_env_deletes` token across the await.
4. **Shutdown order is: stop autosave, drain the executor, then save.** See
   `ServerState.shutdown_storage`. Draining after the final save lets a queued
   write land on top of it and put stale state back on disk. The method is
   idempotent because both the graceful stop and the `atexit` fallback call it.
5. **State taken out of memory before an awaited write has to go back if the
   write fails.** `CloseHandler` pops its panes on the loop and only then awaits
   the undo entry that records them; between those two points the panes exist
   nowhere else, so a write that raises would lose them -- the close is never
   announced, and the next autosave persists an env without them. The rollback
   restores only the ids that are still missing, because the loop kept serving
   and one of them may hold a newer window by then, and it marks the env again
   so the restore reaches disk. The write it was rolling back is then taken
   back too: cancelling the future a handler awaits does not stop the worker
   running the write, so a cancelled close very often records its panes a
   moment after putting them back, leaving them in memory and on the undo stack
   both -- an undo would restore what was never gone, over whatever holds the
   id by then. `forget_closed_panes` submits the removal rather than running
   it, so the single storage worker orders it behind the write it is undoing,
   and it names only the panes that actually came back: an id taken by a newer
   window keeps its entry, because the stack is then the one place the pane it
   closed still exists. Any handler that empties state ahead of a write owes
   the same.

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

`AsyncVisdom` proxies 63 names through `__getattr__` against an explicit
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
| 4k | Async loggers and integrations | `visdom.loggers.*` and `visdom.integrations.optuna` still reach the server through the synchronous client. They are called from training loops and callbacks, which have no running event loop to await on, so an async logger would mean requiring one from the caller. Out of scope deliberately, not overlooked |

### Follow-ups delivered

| # | Item | How it was closed |
|---|------|-------------------|
| 4j | The hyper-parameter pane endpoints wrote on the loop | Both handlers were synchronous: each ran its selection through `ExperimentStore` and called `handler.storage.save_env` inline, and the live-refresh queue drove the update handler from an IOLoop timer. Both now select on the storage worker (`_select_hparams`) from a copy of the resident experiments taken on the loop, and save through `save_env_off_loop`. `LiveUpdateQueue.drain` is a coroutine that awaits each rebuild, and drains never overlap. The update re-checks the window once the read is back, and a refresh whose stored selection was replaced meanwhile is dropped rather than written back. `py/tests/unit/refactoring_docs.py` no longer records any on-loop write, so a new one fails the suite |

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

## Phase 7: CPU Acceleration — **delivered**
**Effort: Large | Risk: Low-Medium | PRs: 15 | Dependencies: none**

Tracked as [issue #1805](https://github.com/fossasia/visdom/issues/1805) and
[issue #695](https://github.com/fossasia/visdom/issues/695). The two describe
one problem from opposite ends: #1805 names the mechanism (`/update` gets
slower as a line plot grows, so appending is O(n²) in the length of the run),
and #695 names the symptom a user sees (a server whose CPU climbs the longer it
is left up). Neither is about SIMD, multiprocessing or a native extension, and
no part of this phase added any — what they are about is work repeated per
point already plotted, per connected client, or per observation already logged.
Removing that is arithmetic, not parallelism.

Phase 4 moved blocking **I/O** off the IOLoop; it did not move **CPU**.
`copy.deepcopy`, `_sanitize_nans` and `jsonpatch.make_patch` are pure Python
and hold the GIL, so "it runs on the storage worker" still spends loop cycles.
This phase is the profile Phase 4's follow-ups 4f and 4h were both gated on.

| PR | What |
|----|------|
| [#1855](https://github.com/fossasia/visdom/pull/1855) | A benchmark harness under `example/benchmarks/`, so a performance claim can be re-run on any two commits |
| [#1875](https://github.com/fossasia/visdom/pull/1875) | Drop the discarded `stringify` length comparison from the `/update` broadcast |
| [#1885](https://github.com/fossasia/visdom/pull/1885) | `NanSafeEncoder` sanitizes once per encode instead of twice |
| [#1888](https://github.com/fossasia/visdom/pull/1888) | Build an append's patch directly instead of diffing a deep copy against the original |
| [#1955](https://github.com/fossasia/visdom/pull/1955) | Keep the layout title helper off plotted points |
| [#1961](https://github.com/fossasia/visdom/pull/1961) | Encode each broadcast once instead of once per recipient |
| [#1970](https://github.com/fossasia/visdom/pull/1970) | Resolve torch and the t-SNE backend on first use rather than at import |
| [#1985](https://github.com/fossasia/visdom/pull/1985) | Read and append experiment metrics without rebuilding the series |
| [#2010](https://github.com/fossasia/visdom/pull/2010) | Cache environment metadata so a search stops re-parsing every env file |
| [#2022](https://github.com/fossasia/visdom/pull/2022) | Validate and group plotted points as arrays instead of one at a time |
| [#2042](https://github.com/fossasia/visdom/pull/2042) | Copy environment data as JSON instead of element by element |
| [#2048](https://github.com/fossasia/visdom/pull/2048) | Build uint8 image grids without widening to float64; let callers set the PNG level |
| [#2056](https://github.com/fossasia/visdom/pull/2056) | Redraw a plot pane only when its figure changed |
| [#2066](https://github.com/fossasia/visdom/pull/2066) | Stop a batched pane update from rewriting state it did not change — *in review as this was written* |
| [#2067](https://github.com/fossasia/visdom/pull/2067) | This record: the phase's closeout |

### 7a. The server — what was repeated, and per what

| Was | Per | Now |
|-----|-----|-----|
| `stringify(pane)` to compare two message lengths, both discarded | plotted point, twice per update | Gone. `UpdateHandler.pane_min_bytes` bounds the pane's encoded size in O(traces) and only encodes when the bound cannot settle it |
| `copy.deepcopy(pane)` + `jsonpatch.make_patch` to discover that an append appended | plotted point | Gone on the append path. `UpdateHandler.update` records its own ops, and `update_packet` returns them |
| `_sanitize_nans` rebuilding the payload in pure Python | encode, twice | Once, and only when the C encoder proves it is needed — `allow_nan=False` turns a non-finite float into a `ValueError` at the first offending value |
| `json.dumps` of one identical message | connected client | Once above the loop, with an early return so an empty room pays nothing |
| `copy.deepcopy(dict(env))` before every save | value in the env, with a dispatch lookup and a memo write each | `copy_json_data` (`py/visdom/utils/shared_utils.py`), reached through `snapshot_env` — an env is JSON by construction, so copying it as JSON shares the scalars and slices the leaf lists at C level |
| `Experiment.from_dict` rebuilding one `Metric` per observation | observation already logged, per read **and** per write | `LazyMetricList` keeps the stored dicts and builds a `Metric` only when one is indexed |
| `json.load` of a whole env file to read the run's metadata off the front of it | environment on disk, per search, per hparams pane, per `GET /experiments/tags` | `JSONStore._read_meta`, one parse point cached on the file's stat identity, under a byte cap |

### 7b. The client and the frontend

The client's cost is not where it looks. A one-point append costs the client
**0.08 ms** — some thirty times less than the wire hop it is about to make — so
no amount of work on that path shows up end to end. Client CPU matters for
three things only: large arrays, media encodes, and `AsyncVisdom`, where it is
GIL-serialised across the bridge's threads. Every client change in this phase
is in one of those three.

- **Per-point Python in the payload builders** (#2022). Five of the six were
  constant-factor; `_markerColorCheck` was the exception and was *quadratic* —
  `ret[Y[k]] = ret.get(Y[k], []) + [v]` rebuilds the accumulated list per
  point, so its cost is Θ(Σ nᵢ²) over the label groups — N²/M in the number of
  points over the number of distinct labels only when the groups are roughly
  balanced, and N² at a single label, which is both the worst case and the
  common one. Skew keeps it near N² for as long as one label still holds a
  constant fraction of the points, however many other labels there are; it
  falls back to linear only once M grows with N and the groups are mostly
  singletons. One 20,000-point scatter with per-point styling paid 817 ms of
  it.
- **A layout helper walking a trace** (#1955). `_normalize_title_strings`
  descends into lists, so running it over a finished trace cost a Python call
  per plotted coordinate looking for a `title` key that cannot be in a list of
  numbers.
- **Imports** (#1970). `import torch` existed to build an isinstance tuple, and
  the openTSNE ladder ran at import to bind a function only `embeddings()`
  calls. Together they were 1.6 s of every `import visdom`, including every
  server start.
- **Media** (#2048). The PNG encode is the whole cost of sending an image and
  is charged per pixel. `opts.compresslevel` is the one lever over it and is
  now exposed; the default is unchanged.
- **Wasted redraws** (#2056, #2066). The frontend's cost is not the redraw it
  has to do, it is the ones it does not have to do: the plot pane's `useEffect` had
  no dependency array, so every unrelated render — a keystroke in a note, a
  filter change — re-ran `Plotly.react` over the whole figure. Eleven
  keystrokes in a note cost up to 1.3 s on a 100,000-point smoothed plot and
  now cost nothing.

### Invariants a later change can break silently

They are here because breaking one costs performance without breaking
behaviour: put the deep copy back on the append path and the patch it produces
is still correct, every behavioural test still passes, and the only symptom is
#1805 returning months later. So each invariant has a guard that asserts what
the code *reaches* rather than what it returns -- a forbidden call, a call
count, a subprocess's `sys.modules` -- and none of them asserts wall-clock,
which would be flaky on a shared runner. They are named here so that a change
to one of these paths can be read against the test that will catch it:

| # | What guards it |
|---|---|
| 1 | `py/tests/unit/update_broadcast.py::test_append_calls_neither_a_deep_copy_nor_make_patch` |
| 2 | `py/tests/unit/shared_utils.py::test_encoder_sanitises_at_most_once` |
| 3 | `py/tests/unit/server_utils.py::test_broadcast_envs_encodes_once_for_every_subscriber`, `…_with_no_subscribers_does_not_encode`, `…_with_an_empty_generator_does_not_encode` |
| 4 | `py/tests/unit/experiment_store.py::test_appending_rebinds_the_series_the_server_is_holding` |
| 5 | `py/tests/unit/data_model.py::test_the_cache_evicts_once_it_is_over_budget`, `test_a_record_larger_than_the_whole_budget_is_still_cached`, `test_recreated_env_is_not_served_from_the_cache`, `test_corrupt_env_is_retried_rather_than_remembered` |
| 6 | `py/tests/unit/tsne.py::test_importing_visdom_does_not_pull_in_a_backend` |
| 7 | `playwright/tests/plot_redraw.spec.js`, "typing a note does not redraw the plot" |

What none of them covers is the *reasoning* below drifting from the code: a
guard says the call does not happen, not why it must not, and nothing checks
that this record still describes what is there.

1. **An append neither copies the pane nor diffs it.** `update_packet`'s
   `appendable` fast path must not reach `copy_json_data`, `copy.deepcopy` or
   `jsonpatch.make_patch`: those are the two costs #1805 is about, and they are
   O(points already plotted) while the append itself is O(points added). The
   fast path owes two things the diffed path got for free. It must bump the
   version and reroll `contentID` itself, *and* put both in the patch, or the
   frontend discards the update and reloads the environment — and it must
   return an empty patch when `update` recorded no ops, or
   `vis.line(X=[], Y=[], update="append")` repaints the pane on every empty
   batch where the diffed path correctly said nothing.
2. **`NanSafeEncoder` overrides `iterencode` and not `encode`.**
   `JSONEncoder.encode` calls `self.iterencode` internally, so overriding both
   sanitizes every payload twice before the C encoder ever sees it — which is
   what it did, at 3x the cost of plain `json.dumps`. The trigger must stay
   `allow_nan=False` rather than a scan of the encoded output: a pane whose
   title merely contains the string `"NaN"` is not exotic, and scanning
   regresses that case to a full encode, a full sanitize and a full re-encode.
3. **A broadcast encodes once per message, and not at all for nobody.**
   `broadcast_envs`, `send_to_sources` and `broadcast_layouts`: the
   encode belongs above the `for sub in …` loop, and the early return on an
   empty recipient list is required rather than a bonus: the loop body it
   replaces never ran for an empty room, so a bare hoist would make an
   unattended server encode a full pane on every close. A caller-supplied
   recipient list must be materialised before it is tested, because an empty
   generator is still truthy — which is what the `list(target_subs)` in
   `broadcast_envs` is for. A `dict_values` view sizes itself and needs no
   such copy.
4. **A stored blob is never edited in place.** Two separate things now depend on
   it. `experiments_handler._resident_experiments` hands stored blobs to the
   storage worker **uncopied**, and `_read_meta` hands the *same* dict back to
   repeat readers — so an in-place edit no longer corrupts just its own read.
   `ExperimentStore` writes by rebinding `env["experiment"]`, and
   `LazyMetricList.append` copies the underlying list when it is marked
   `_shared`. Appending in place instead grows a list the worker is iterating:
   a `RuntimeError` out of `/experiments/hparams`, intermittently.
5. **The metadata cache key is the file's whole stat identity, and the cache is
   bounded.** The key is six fields — `st_mtime_ns`, `st_ctime_ns`, `st_size`,
   `st_ino`, `st_dev` and `st_mode` — and each is load-bearing. `st_mtime`
   alone will not do: it is whole seconds on some filesystems, so a rewrite in
   the same second as the read before it would be missed. `st_ino` closes most
   of that, because `_atomic_write` ends in `os.replace` and a replaced file is
   a new inode whatever its timestamps say. `st_mode` and `st_ctime_ns` cover
   the one way a file can change what it answers without its contents moving at
   all — `chmod -r` makes the next read fail without touching mtime, size or
   inode, and a record cached while the file was readable would otherwise go on
   being served after access was revoked. Only a *successful* read is stored: a
   failure needs nothing in the key to move, so caching one would outlive its
   cause and keep the env out of `list_envs` and every `/experiments` answer
   until the file was rewritten. The stat is taken *before* the parse, so the
   cache can file newer content under an older key -- the next read stats
   again, sees the stored key no longer match, and re-parses -- but never
   older content under a newer key. The re-parse is driven by the key moving:
   a rewrite that left all six fields identical would still be served from the
   cache, which is why the key is the whole stat identity rather than a
   timestamp. The byte cap is not optional
   either: a record is flat ~18 KB however many points the window holds, but a
   metric series is not, so 100 environments of 20,000 observations cached
   595 MB before `meta_cache_bytes` existed. The cap is a budget rather than a
   hard ceiling: `_evict_locked` stops at the last entry standing, so a single
   record larger than the whole budget is still held — it was just read and
   the caller holds that blob anyway. The real bound is the budget or the
   biggest single experiment on disk, whichever is larger.
6. **Nothing at module scope may import torch, scikit-learn or a t-SNE
   backend.** They cost more than the rest of `import visdom` put together.
   `_resolve_torch_types` reads `sys.modules` instead, which is a complete test
   and not a heuristic — a caller cannot be holding a tensor without having
   imported torch themselves. It must resolve `Tensor` and `nn.Parameter`
   *separately*: a partially initialised torch has one and not the other, and
   dropping the type it does have passes a real tensor through unconverted, to
   reach the server as an object it cannot serialise. Neither result may be
   cached — a reload keeps the same module object while rebinding the classes,
   and a stale entry there is silent.
7. **The plot pane's redraw effect keeps its dependency array.** It had none,
   so every unrelated render re-ran `Plotly.react` over the whole figure. The
   array is the eight values the redraw actually reads, and two of them are
   there for non-obvious reasons: `propertyEdits` because the property list
   mutates `content` in place and so changes nothing the array could otherwise
   see, and `annotations.modebarButton` only because it is `useMemo`'d — a
   fresh object literal per render would defeat the whole array. Adding a value
   the redraw reads without adding it here brings back a stale figure; adding
   one it does not read brings back the wasted redraws.

[#2066](https://github.com/fossasia/visdom/pull/2066) was still in review when
this record was written. It adds one more invariant of the same kind, which
belongs in the list above once it lands: **a pane's layout item is replaced,
not mutated.** react-grid-layout deep-compares the layout array against the
previous one and the previous array shares its items, so an in-place edit is
invisible to it and a pushed `opts.height` is silently dropped. Its flush must
also read `latestRef.current.storeData` rather than the render closure that
armed its timer, and the patches must stay *outside* the `setStoreData`
updater: updaters have to be re-entrant, and `jsonpatch.applyPatch` runs there
with `mutateDocument`, so an add-to-array op applied twice appends the point
twice.

### Benchmarks — the phase end to end

`example/benchmarks/` is the harness #1855 added, and these are its numbers for
the commit before the phase against the commit after it, on one machine
(py3.12, in-process, p50). The absolute milliseconds are this machine's; the
column that carries the finding is the one that does not move.

**The server appending one point to a line plot** (`update_append.py`):

| points already plotted | before | after |
|---|---|---|
| 500 | 1.155 ms | 0.026 ms |
| 4,000 | 7.569 ms | 0.026 ms |
| 20,000 | 38.242 ms | 0.026 ms |

That is the whole of #1805 in one table, and the speedup at the bottom row
(1,470x) is the least interesting number in it. The point is that the "before"
column grows in proportion to the data already plotted — which makes a training
run cost time quadratic in its own length, and makes the server appear to slow
down the longer it is left up, which is #695 — and the "after" column is flat.
26 microseconds is 38,000 appends a second, so the append path is no longer
what a run waits for.

**The rest**, same two commits:

| Workload | Before | After | |
|---|---|---|---|
| `import visdom` (interleaved subprocesses, median of 5) | 1,795 ms | 160 ms | 11.2x |
| `NanSafeEncoder` over plain `json.dumps`, 20,000 points | 3.1x overhead | 1.0x | — |
| Client `line()`, 20,000 points | 67.4 ms | 23.1 ms | 2.9x |
| Client `scatter()` with per-point style, 20,000 points | 260.1 ms | 59.6 ms | 4.4x |
| Client `heatmap()`, 20,000 points | 39.7 ms | 22.8 ms | 1.7x |
| Client one-point append | 0.147 ms | 0.076 ms | 1.9x |
| Warm metadata scan, 20 envs x 200 observations | 112.8 ms | 0.4 ms | 282x |
| Env snapshot, 20 panes x 20,000 points | 157.8 ms | 15.6 ms | 10.1x |
| `broadcast_envs`, 120 envs, 32 subscribers | 2.267 ms | 0.011 ms | 206x |

Every client payload in that table is **byte-identical** between the two
commits; the sizes are reported alongside the timings for exactly that reason.
Media encodes are **1.0x** in `payload_build.py` and are meant to be: both of
its media workloads are random integers widened to `float64`, so neither of
#2048's levers can apply there -- the grid change needs uint8 input, and the
PNG level needs compressible content, where an incompressible image costs the
same bytes in the same time at every level. `media_encode.py` is the benchmark
that can see them, and its fixture is a smooth, correlated uint8 picture for
exactly that reason.

### What is left, and the one number that disappoints

**The metadata cache is all-or-nothing against `meta_cache_bytes`, whose
default is `DEFAULT_META_CACHE_BYTES`, currently 8 MB.** A search touches every
environment exactly once, in order, which is the worst access pattern LRU has:
if the working set does not fit, every entry is evicted before its next use and
the cache returns almost nothing. There is no middle. (8 MB is a budget rather
than a hard ceiling: eviction stops at the last entry standing, so a single
record heavier than the whole budget is held anyway.) Measured at 20
environments holding a 20,000-point window each:

| observations per env | warm scan |
|---|---|
| 500 | 0.4 ms |
| 1,000 | 0.4 ms |
| 1,300 | 143.5 ms |
| 2,000 | 155.4 ms |

The cliff sits where the arithmetic puts it. `meta_weight` charges
`META_ENTRY_BYTES` once per cached record and
`META_SEQUENCE_BYTES + observations x META_OBSERVATION_BYTES` for the metric
series, then walks everything else the record holds — the mapping itself, a
slot per key, the name, the params, the tags and the description — so the
series term is a floor rather than the whole weight, and "about 1,300
observations each" is what 8 MB bought across 20 environments of *this*
fixture. A run logging large parameter values hits the cliff earlier. It is a
cliff either way, not a slope: past it the warm scan costs 143.5 ms, which is
re-parsing every file plus the cache's own bookkeeping, where this table's top
rows get 282x. Raising `meta_cache_bytes` fixes it; nothing sizes it
automatically, and LRU is the wrong policy for a full sweep. That is follow-up
7a below and it is the largest remaining item in the phase.

`stringify` is still 2.5x plain `json.dumps` at every size. #1875 and #1888
removed it from the append path rather than making it cheaper, and it is the
pretty-printer the save path and the non-append `/update` still use.

### Follow-ups not taken

| # | Item | Why it was left |
|---|------|-----------------|
| 7a | Size `meta_cache_bytes` from the environment directory, or make eviction scan-aware | The table above is the argument for it. LRU is actively wrong for a pattern that touches every key once in order; MRU, or simply not evicting during a sweep, would hold the early entries instead of the ones about to be re-read. Left because the right policy depends on whether a deployment's scans or its single-env reads dominate, which is a measurement nobody has taken on a real install |
| 7b | Copy-on-write at window granularity instead of `copy_json_data` | This is what the phase originally planned for the env snapshot. It needs a per-*window* dirty signal and `ServerState.mark_dirty` is per-env, it keeps a second copy of every environment resident, and its failure mode is persisting a stale pane. The copier got 10x with none of that, and it helps the one-hot-window case COW cannot. If COW is revisited it must be measured against the copier, not against `copy.deepcopy` |
| 7c | Memoize the topbar and the modals | `EnvControls`, `ViewControls`, `FilterControls`, `ConnectionIndicator`, `EnvModal` and `ViewModal` are none of them memoized, so every pane update rebuilds all six. After #2056 and #2066 they and react-grid-layout's `GridItem` re-wrap are what is left of per-update element creation. Not taken because caching rendered pane elements was tried first and measured as a **wash** on a production bundle — 1.29x on a dev build, 1.00x on `webpack.prod.js` — so this family of changes needs a prod-build measurement before any of it is worth committing |
| 7d | Make `stringify` cheaper, or stop using it where the output is not read by a human | It is 2.5x `json.dumps` because it pretty-prints. The save path's output is read by a human occasionally; the non-append `/update` path's is not read by anyone |
| 7e | The polling transport's second escape pass | Polling escapes the message a second time, which is a wire-protocol difference between the two transports rather than a saving. Changing it needs `js/` and a rebuilt bundle, and Phase 6 is where the two transports get reconciled |
| 7f | Drop `"compiled_template_cache": False` from the app settings | It is set explicitly at `py/visdom/server/app.py:108`, so Tornado recompiles the templates on every page render rather than caching them as it would by default. Removing one line would stop that, but it is the page-render path rather than the data path, and neither #1805 nor #695 points at it — so it wants its own measurement and its own PR rather than a free ride on this phase |

### Follow-ups delivered

| # | Item | How it was closed |
|---|------|-------------------|
| 4f | Per-env write locks instead of one global storage worker | Gated on "only worth it once a profile shows the single worker is the bottleneck". The profile exists now and it does not: what the save path spent was the `copy.deepcopy` ahead of it, on the loop, which #2042 cut by 10x. The worker is not the queue. Still not worth doing, now for a measured reason rather than an assumed one |
| 4h | Native async plotting bodies in `AsyncVisdom` | Same gate — "only worth doing if the bridge's thread pool shows up in a profile". It does not. What was actually expensive in a plotting body was per-point Python in the payload builders (#2022) and the import cost paid once (#1970), and both were fixed without forking a single method. The bar for forking 40+ plotting methods is now higher than before, not lower |

---

## Open Issues Alignment

| Issue | Related Phase | How Addressed |
|-------|---------------|---------------|
| [#771](https://github.com/fossasia/visdom/issues/771) (client 10x slower than the caller's script) | Phase 4 | **Delivered** — preflight removed, `AsyncVisdom` added; numbers above |
| [#1805](https://github.com/fossasia/visdom/issues/1805) (`/update` gets slower as a line plot grows) | Phase 7 | **Delivered** — an append no longer copies or diffs the pane; the cost is flat in the data already plotted |
| [#695](https://github.com/fossasia/visdom/issues/695) (server CPU climbs the longer it is up) | Phase 7 | **Largely delivered** — the per-point, per-recipient and per-observation repeats are gone. The remaining growth with uptime is the metadata cache going cold past its byte cap; see follow-up 7a |
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
Phase 7 (CPU)   ✔ done, independent of all of them
```

Phases 1 & 2 can start immediately in parallel. Phase 5 can proceed independently after Phase 1.

Phase 4 was planned as a dependant of Phase 3 and did not turn out to be one — the
disk I/O already had a single owner. Phase 6 keeps its Phase 3 dependency, and it
inherits one thing from Phase 4: the protocol it standardizes is now spoken by two
clients, `Visdom` and `AsyncVisdom`, over two transports each.

Phase 7 depended on none of them. It is a profile and the arithmetic that
follows from one, so it touched the client, the server and the frontend without
needing any of the three restructured first — and it closed Phase 4's two
gated follow-ups (4f, 4h) by measuring them rather than by doing them.

**Estimated total: 10-13 PRs across the remaining phases.**
Phase 4 took 11 of its own, and Phase 7 took 15.

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
| `py/visdom/__init__.py` | 5,396 | Phases 1, 5, 7 |
| `py/visdom/async_client.py` | 940 | Phase 4 (new) |
| `py/visdom/server/server_state.py` | 398 | Phase 4 (new); future home for Phase 3 |
| `py/visdom/server/handlers/web_handlers.py` | 2,450 | Phases 2, 3, 4, 7 |
| `py/visdom/server/handlers/socket_handlers.py` | 958 | Phases 2, 3, 4, 6, 7 |
| `py/visdom/server/handlers/base_handlers.py` | 149 | Phase 2 |
| `py/visdom/utils/server_utils.py` | 1,355 | Phases 2, 3, 4, 7 |
| `py/visdom/server/app.py` | 381 | Phases 3, 4 |
| `py/visdom/server/run_server.py` | 486 | Phase 4 |
| `py/visdom/utils/shared_utils.py` | 416 | Phases 1, 7 |
| `py/visdom/data_model/json_store.py` | 705 | Phase 7 |
| `py/visdom/experiments/models.py` | 481 | Phase 7 |
| `js/main.js` | 1,298 | Phase 7 |
| `js/panes/PlotPane.js` | 544 | Phase 7 |

Line counts drift; they are here for relative size, not as an assertion.
