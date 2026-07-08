# Testing Instructions

Two layers: **pytest** for Python unit tests (pure functions, server utils, window/env lifecycle) and **Cypress 9** for E2E and visual regression. Demo scripts remain useful for manual/visual validation.

## Run Python Tests (pytest)

```bash
pip install -r test-requirements.txt   # includes pytest, pytest-cov
pytest                                 # runs the tracked suite under py/tests/
pytest -m "not server"                 # skip tests that need a live server (CI default)
```

Config lives in `pyproject.toml` (`[tool.pytest.ini_options]`): discovery is scoped to
`py/tests/` and `pythonpath = ["py"]` makes `import visdom` work without an editable install.
Experimental `test_*.py` scripts in the repo root (and `test/`) are intentionally out of scope.

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

- Place in `py/tests/`, name files `test_*.py`, classes `Test*` (unittest `TestCase` or plain
  pytest functions both work — pytest auto-discovers unittest).
- Keep them hermetic (no running server). A test that genuinely needs a live server must be
  marked `@pytest.mark.server` so CI can deselect it.
- Start with simple hermetic tests (e.g., `test_smoke.py`) and add focused unit tests for
  server/window/env lifecycle code as coverage grows.

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
