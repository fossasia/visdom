# Frontend Instructions

## Stack

React 17, Plotly.js (v2.11.1 CDN), ReactGridLayout, D3, Three.js, MathJax, Webpack 5, Babel, ESLint + Prettier.

## Key Files

- `js/main.js` — Entry point: grid layout, env management, pane rendering.
- `js/api/ApiProvider.js` — WebSocket connection, message routing. Add new commands here.
- `js/api/Legacy.js` — Polling fallback.
- `js/panes/` — Visualization components. Use `forwardRef` + `React.memo` pattern.
- `js/settings.js` — Register pane types in `PANES`, set sizes in `PANE_SIZE`.
- `js/topbar/` — Connection indicator, env/filter/view controls.
- `js/modals/` — Environment and view management dialogs.

## Build

- Production: `npm run build` (minified)
- Development: `npm run dev` (watch mode, source maps)
- Output: `py/visdom/static/js/main.js` — never edit manually

## Lint & Format

- Run `npm run lint` before committing, max line length 80
- Import sorting enforced (`simple-import-sort`)
- `Plotly` is a readonly global (CDN-loaded, not bundled)

## CDN Dependencies

Downloaded by `build.py` on first run: Plotly, jQuery, Bootstrap, React 16.2.0, MathJax, D3, SJCL. Note: `static/` has React 16.2.0, `main.js` uses React 17.0.2 — known legacy setup.

## Adding Dependencies

Use `yarn add <pkg>`. Consider bundle size. CDN deps are in `build.py`, not `package.json`. Ask before adding.
