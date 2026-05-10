# Testing Instructions

Cypress 9 for E2E and visual regression. No Python unit tests — validation is via demo scripts and Cypress.

## Run Tests

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

## CI

- Python 3.8, 3.9, 3.10 matrix, both WebSocket and polling modes
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
