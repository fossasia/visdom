# Testing Instructions

Two layers: **pytest** for Python unit tests (pure functions, server utils, window/env lifecycle) and **Playwright** for E2E and visual regression. Demo scripts remain useful for manual/visual validation.

## Run Python Tests (pytest)

```bash
pip install -r test-requirements.txt   # includes pytest, pytest-cov
pytest                                 # runs the tracked suite under py/tests/
pytest -m "not server"                 # skip tests that need a live server (CI default)
```

Config lives in `pyproject.toml` (`[tool.pytest.ini_options]`): discovery is scoped to
`py/tests/`, and `pythonpath = ["py", "py/tests"]` makes both `import visdom` and
`import testutils` work without an editable install. Because discovery is scoped by `testpaths`,
experimental `test_*.py` scripts in the repo root (and `test/`) stay out of scope; `testutils/` is
excluded via `norecursedirs` so helpers are importable but never collected.

## Run E2E / Visual Tests (Playwright)

```bash
npx playwright install chromium     # Install the browser once
npm test                            # WebSocket functional tests
npm run test:polling                # Polling functional tests
npm run test:gui                    # Interactive UI
npm run test:init                   # Generate baseline screenshots
npm run test:visual                 # Compare visual screenshots
```

Make sure port `8098` is available. The Playwright configuration starts an
isolated Visdom server automatically.

## Writing Tests

- Place specs in `playwright/tests/`, follow `basic.spec.js`, `pane.spec.js`, and
  `text.spec.js` patterns
- Put shared browser and demo helpers in `playwright/support/`
- Run `test:init` before `test:visual` for baselines

## Test Files

`basic.spec.js` (connection), `pane.spec.js` (CRUD), `text.spec.js`,
`image.spec.js`, `properties.spec.js`, `modal.spec.js`, `misc.spec.js`,
`screenshots.init.spec.js` (baseline), `screenshots.spec.js` (comparison).

## Writing Python Tests

### Where a test goes

```
py/tests/
  conftest.py        shared fixtures, auto-loaded by pytest
  testutils/         importable helpers (fakes, payload builders, HTTP base class)
  unit/              pure logic: no Application, no I/O beyond tmp_path
  integration/       in-process Application, real HTTP, or handler dispatch
```

`py/tests/` has **no** `__init__.py` on purpose — `setup.py` runs `find_packages(where="py")`,
so a package there would ship a top-level `tests` distribution to users. `testutils/` is a
package and is reachable because `py/tests` is on `pythonpath`.

Everything under `py/tests/` must be **hermetic and collectable**: no externally launched
server, no browser, no assertion a human has to make. A script that needs a live server and is
judged by looking at the UI goes in `example/manual/` instead — see
`example/manual/visual_check.py`. Pixel correctness is Playwright's job, not pytest's.

- Name a file after what it covers — `integration/window_types.py`, not
  `integration/test_window_types.py`. The `unit/` and `integration/` directories already say these
  are tests, so the filename does not repeat it; `python_files = ["*.py"]` in `pyproject.toml`
  collects them, and `norecursedirs` keeps `testutils/` importable but uncollected. Test
  *functions* and `Test*` classes still need their usual prefixes.
- **Which style you use depends on whether the test needs HTTP.**

  | Test needs | Write | Why |
  |---|---|---|
  | no `Application`, or a handler object | plain `def test_*()` functions | fixtures and `parametrize` both work |
  | a real HTTP round trip | a `VisdomHTTPTestCase` subclass | `tornado.testing.AsyncHTTPTestCase` is a `unittest.TestCase`, and that is what starts the app |

  **pytest cannot inject fixtures into `TestCase` methods** — `def test_x(self, app)` fails, and
  only autouse fixtures reach them. `@pytest.mark.parametrize` does not work on them either; use
  a small `_assert_*` helper called from several one-line test methods instead. A module-level
  `pytestmark = pytest.mark.integration` **does** apply to `TestCase` classes, so always set one.
- Keep them hermetic. A test that needs an **externally launched** server must be marked
  `@pytest.mark.server` so CI can deselect it; nothing in the tracked suite needs one today.

### Shared fixtures (`py/tests/conftest.py`)

| Fixture | Gives you |
|---|---|
| `env_path` | disposable environment directory |
| `store` / `spy_store` | `JSONStore` / one that records backend calls |
| `app` / `app_factory` | `Application` on a temp `env_path`; factory for reload assertions |
| `handler` / `app_handler` | duck-typed handler, standalone or sharing an `Application`'s state |
| `fake_socket` | records `write_message`; `.commands()` and `.last(cmd)` for assertions |
| `offline_client` | `Visdom(send=False)` — never opens a connection |
| `capture_send` | runs a client call and returns the payload it would have sent |

`reset_warn_once` is autouse: `shared_utils.warn_once` dedupes against a module-level set, so
without it a warning raised by one test silently suppresses the same warning in another.

### HTTP tests

Subclass `testutils.VisdomHTTPTestCase`. It starts the app in-process on an ephemeral port, gives
every test a fresh `env_path` that is cleaned up in `tearDown`, and provides `post_json`,
`create_window`, `create_text_window`, `update`, `close_window`, `win_exists`, `get_win_data`,
`get_envs`, `save` and `panes`, on top of `AsyncHTTPTestCase`'s own `fetch`. Override the
`app_kwargs` class attribute to vary server configuration:

```python
class TestReadonlyRoutes(VisdomHTTPTestCase):
    app_kwargs = {"readonly": True}
```

`AsyncHTTPTestCase` already runs the `Application` in-process on its own `IOLoop`, driving each
request through `io_loop.run_sync`. **Do not replace it with a background thread, a hand-rolled
`asyncio` loop, or an out-of-process server** — none of that buys anything, and it was tried and
reverted. The `TestCase` style is the accepted cost of using it.

Because fixtures cannot reach these tests, anything shared goes on the class: `self.env_path` for
the temp directory, and a small base class between `VisdomHTTPTestCase` and your test classes for
helpers several of them need (see `WindowTypeTestCase` in `integration/window_types.py`).
Need a second `Application` over the same directory, for a reload assertion? Construct it directly
with `Application(port=8097, env_path=self.env_path)` — `app_factory` is not available here.

### Markers

`unit`, `integration`, `slow`, and `server` are registered in `pyproject.toml`. Set
`pytestmark = pytest.mark.unit` or `pytest.mark.integration` at the top of every new file; it
works for both plain functions and `TestCase` classes. Many older files predate this and carry no
marker, so `-m integration` currently under-selects.

## CI

- `python-tests.yml` runs `pytest -m "not server"` on a Python version matrix for every pull
  request (and on pushes to master/dev)
- Visual regression compares PR screenshots against base branch
- `update-js-build-files.yml` auto-compiles JS on master
- `pypi.yml` publishes to PyPI when VERSION changes

## Regression Check

Run `python example/demo.py` on your branch and a clean branch, visually confirm no differences.

## Debugging

- Verbose logs: `visdom -logging_level DEBUG`
- Clean state: `visdom -env_path /tmp`
- Raw window data: `/win_data` endpoint
- Source maps: `npm run dev`
- WebSocket inspection: Browser DevTools → Network → WS tab
- Blue screen → check `py/visdom/static/` for missing CDN files
- `@generated` lint errors → discard changes to `py/visdom/static/`
