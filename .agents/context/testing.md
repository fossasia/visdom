# Testing Context

## Framework

- **Cypress 9** for end-to-end and visual regression testing
- **No Python unit test suite** — Python behavior validated via demo scripts and Cypress E2E tests

## Test Server Setup

Always use a fresh server on port `8098` with `-env_path /tmp`:

```bash
visdom -port 8098 -env_path /tmp
```

## Commands

| Command | Purpose |
|---------|---------|
| `npm run test:init` | Generate Cypress baseline screenshots |
| `npm run test` | Run all Cypress tests (CLI) |
| `npm run test:gui` | Run Cypress tests (interactive GUI) |
| `npm run test:visual` | Run visual regression tests only |

## Test Structure (`cypress/`)

| Path | Purpose |
|------|---------|
| `integration/basic.js` | Server connection, environment selection |
| `integration/pane.js` | Window/pane CRUD operations |
| `integration/text.js` | Text pane functionality |
| `integration/image.js` | Image pane operations |
| `integration/properties.js` | Interactive property widget tests |
| `integration/modal.js` | Modal dialog interactions |
| `integration/misc.js` | Miscellaneous feature tests |
| `integration/screenshots.init.js` | Baseline screenshot capture |
| `integration/screenshots.js` | Visual regression comparison |
| `plugins/` | Cypress plugins (pixelmatch for image comparison) |
| `support/` | Support files and custom commands |

## Visual Regression

- Uses `pixelmatch` for pixel-level screenshot comparison
- Run `npm run test:init` first to establish baseline, then `npm run test:visual`

## CI Workflow (`process-changes.yml`)

| Job | Description |
|-----|-------------|
| **lint-js** | ESLint check (Node 16) |
| **lint-py** | Black formatting check (v23.1.0) |
| **install-and-build** | Build JS, upload artifacts |
| **visual-regression-test-init** | Baseline screenshots against base branch |
| **visual-regression-test** | Compare PR screenshots to baseline |
| **functional-test (websocket)** | Cypress on Python 3.8, 3.9, 3.10 |
| **functional-test (polling)** | Cypress with polling mode |

## CI Python Versions

3.8, 3.9, 3.10 (matrix strategy)

## Test Dependencies

`test-requirements.txt`: matplotlib, numpy, av, torch-cpu

## Regression Validation

Run `python example/demo.py` on both your branch and a clean branch, visually confirm no differences.

## Other CI Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `update-js-build-files.yml` | Push to master (js/** changed) | Auto-compiles main.js |
| `pypi.yml` | Push to master (VERSION changed) | Publishes to PyPI |
| `issue-scripts.yml` | Issue comment | Auto-responds to "assign me" comments |

## Debugging Tips

### Server-Side

- `visdom -logging_level DEBUG` for verbose logging
- `/win_data` endpoint to dump raw window JSON
- `visdom -env_path /tmp` for clean state

### Frontend

- Browser DevTools → Network → WS tab for WebSocket messages
- `npm run dev` for debuggable builds with source maps
- `Plotly` is a global accessible in browser console

### Common Error States

| Symptom | Fix |
|---------|-----|
| Blue screen, no visualizations | Check `py/visdom/static/` for missing CDN files |
| "Socket refused connection" | Start server, check port |
| `win does not exist` on update | Check `vis.win_exists()` first |
| Layout broken | Clear browser localStorage |
| Visual regression failures | Re-baseline with `test:init` |
| `@generated` lint errors | Discard changes to `py/visdom/static/` |
