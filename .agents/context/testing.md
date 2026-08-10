# Testing Instructions

Two layers: **pytest** for Python unit tests (pure functions, server utils, window/env lifecycle) and **Cypress 9** for E2E and visual regression. Demo scripts remain useful for manual/visual validation.

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

## Run E2E / Visual Tests (Cypress)

```bash
visdom -port 8098 -env_path /tmp   # Always start fresh server first
npm run test:init                   # Generate baseline screenshots
npm run test                        # Run all tests (CLI)
npm run test:gui                    # Interactive GUI
npm run test:visual                 # Visual regression only
```

Always use port `8098` and `-env_path /tmp` for isolation.

## Writing Tests

- Place in `cypress/integration/`, follow `basic.js`, `pane.js`, `text.js` patterns
- Visual regression uses `pixelmatch` in `cypress/plugins/`
- Run `test:init` before `test:visual` for baselines

## Test Files

`basic.js` (connection), `pane.js` (CRUD), `text.js`, `image.js`, `properties.js`, `modal.js`, `misc.js`, `screenshots.init.js` (baseline), `screenshots.js` (comparison).

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

- Name a file after what it covers — `unit/window_builder.py`, not `unit/test_window_builder.py`.
  The `unit/` and `integration/` directories already say these are tests, so the filename does not
  repeat it; `python_files = ["*.py"]` in `pyproject.toml` collects them. Test *functions* still
  need the `test_` prefix. **Write plain `def test_*()` functions, not `unittest.TestCase`
  subclasses.** pytest still runs `TestCase` (much of the suite predates this rule), but
  **pytest cannot inject fixtures into `TestCase` methods** — `def test_x(self, app)` fails.
  Only autouse fixtures reach them. A `TestCase` therefore cannot use anything in the table
  below, and cannot use `@pytest.mark.parametrize` either.
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

HTTP tests are the one exception to the plain-function rule today: subclass
`testutils.VisdomHTTPTestCase`, which starts the app in-process on an ephemeral port, gives every
test a fresh `env_path` that is cleaned up, and provides `post_json`, `create_window`,
`create_text_window`, `get_envs`, `get_win_data`, `win_exists` and `panes`. Override the
`app_kwargs` class attribute to vary server configuration.

It is a `TestCase` only because `tornado.testing.AsyncHTTPTestCase` is one, so the fixtures above
are unavailable inside it. It is scheduled to be replaced by an equivalent `visdom_server` fixture
that runs the app on a background event loop and talks to it with `requests`, which removes the
last reason for any `TestCase` in this suite.

### Markers

`unit`, `integration`, `slow`, and `server` are registered in `pyproject.toml`.

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
