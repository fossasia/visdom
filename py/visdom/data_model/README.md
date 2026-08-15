# `visdom.data_model` — the storage abstraction layer

This package is the single place Visdom's server goes to persist and read back
its state. It defines **what** Visdom needs from storage (`DataStore`) apart from
**how** that storage works (`JSONStore`, the JSON-file backend), so a different
backend — a database, an object store — can be dropped in later without touching
any caller.

## Why an abstraction

Historically the server read and wrote environment JSON files directly from the
handlers and app code, with the same path-building, hashing and sanitisation
logic copied across several call sites. This layer replaces that with one
interface:

- Every save/load/delete/list, every layout and undo read/write, funnels through
  a `DataStore` instance held on the application as `Application.storage`.
- Nothing outside this package touches env/layout/undo files on disk directly.
- Swapping the backend is a one-line change (construct a different `DataStore`);
  the rest of the server is unaware of the storage medium.

## The `DataStore` interface

`base.py` defines the abstract contract. An *environment* is the in-memory dict
the server holds, of the form `{"jsons": {...}, "reload": {...}}`, keyed by its
id (`eid`).

| Group | Method | Purpose |
|-------|--------|---------|
| Environments | `save_env(eid, env_data)` | Persist one environment. |
| | `save_envs(state, eids)` | Persist a named subset of `state`; returns the ids written. |
| | `save_all(state)` | Persist every environment in `state`. |
| | `load_env(eid)` | Read one environment's data (`{}` if absent). |
| | `list_envs()` | Ids of all stored environments. |
| | `delete_env(eid)` | Remove one environment. |
| | `env_exists(eid)` | Whether an environment is stored. |
| Layouts | `save_layouts(layouts)` | Persist the saved-views layout blob. |
| | `load_layouts()` | Read the layout blob (`""` if none). |
| Undo | `load_undo(eid)` | An env's closed-pane undo stack (`[]` if none). |
| | `save_undo(eid, stack)` | Persist an env's undo stack. |
| | `clear_undo(eid)` | Remove an env's undo history. |

Three separate save operations exist on purpose: callers persist one env, a
named subset, or everything, and each maps to a distinct server code path
(fork/upload/main-write, the save handler, and the atexit/save-all flow).

## The `JSONStore` backend

`json_store.py` is the default backend, backward compatible with the classic
`~/.visdom/*.json` layout. It is constructed with an `env_path`:

```python
from visdom.data_model import JSONStore
store = JSONStore("/path/to/env_dir")   # env_path=None ⇒ in-memory, no-op
```

On-disk layout under `env_path`:

```
<env_path>/
  <eid>.json                 # one file per environment
  hash_<sha256>.json         # fallback for ids too long to be a filename
  view/layouts.json          # saved-views layout blob
  .undo/<eid>.json           # per-env closed-pane undo stack (atomic writes)
  .undo/hash_<sha256>.json   # undo fallback for over-long ids
```

Key behaviours:

- **In-memory mode.** When `env_path is None` persistence is disabled and every
  operation is a no-op (`load_*` return empty, `save_*`/`delete` do nothing).
  This matches Visdom's in-memory-only server mode — there is nothing on disk to
  store, search or compare.
- **Id sanitisation & path-traversal guard.** Every id is run through
  `_safe_eid` (strips whitespace, neutralises `/`, `\`, newlines) and resolved
  under `env_path`; an id such as `../evil` that would escape `env_path` is
  rejected, so a crafted id can never read or write outside the env directory.
  Saves, loads, deletes and existence checks all funnel through the same path
  helpers so they agree on the file a given id maps to.
- **Long-id fallback.** An id whose plain filename would exceed the filesystem
  limit is stored as `hash_<sha256>.json` with its real id kept in a `name`
  field inside the file; `list_envs` resolves those back to the real id.
- **Byte-stable JSON.** Env files are written with `NanSafeEncoder` so `NaN`/inf
  survive the round trip; `load_env` returns only the canonical `jsons`/`reload`
  fields (plus an `experiment` metadata blob when present), dropping internal
  bookkeeping like the hashed-file `name`.
- **Atomic undo writes.** `save_undo` writes to a temporary file and `os.replace`s
  it into place so a crash cannot leave a half-written undo stack.

## How it is wired

```python
# server/app.py
self.storage = JSONStore(env_path)   # set before load_state()
self.state   = self.load_state()     # iterates storage.list_envs()/load_env()
```

Handlers receive it via `BaseHandler.initialize` (`self.storage = app.storage`)
and use it for every persistence operation — saving, deleting, forking,
uploading, layouts and undo. `LazyEnvData` (in `utils/server_utils.py`) also
reads through the store, so an env is only loaded from disk on first access.

## Adding a new backend

Subclass `DataStore`, implement every abstract method, and construct it in place
of `JSONStore` in `app.py`. Because callers depend only on the interface, no
handler or app logic changes. A backend is free to ignore the on-disk layout
above entirely (e.g. a database backend stores rows, not files) as long as it
honours the method contracts — notably returning `{}`/`[]`/`""` for absent data
and treating a null/disabled destination as a no-op.
