# Frontend Context

## Tech Stack

- **React 17** with functional components and hooks
- **Plotly.js** (v2.11.1, loaded via CDN) for all chart rendering
- **ReactGridLayout** (v0.16.6) for draggable/resizable window grid
- **D3** (selection, drag, zoom, polygon) for network graph and lasso selection
- **Three.js** (v0.105.2) for 3D mesh/surface rendering
- **MathJax** (v2.7.5) for LaTeX rendering
- **Savitzky-Golay filter** for line plot smoothing
- **Webpack 5** for bundling; **Babel** for transpilation
- **ESLint** + **Prettier** for code quality

## Source Structure (`js/`)

| Path | Purpose |
|------|---------|
| `main.js` | App entry: grid layout, env management, pane rendering |
| `api/ApiProvider.js` | WebSocket connection, message routing, env queries |
| `api/ApiContext.js` | React Context for API state |
| `api/Legacy.js` | Polling fallback |
| `panes/Pane.js` | Base pane: title bar, resize, close/download |
| `panes/PlotPane.js` | Plotly chart renderer |
| `panes/TextPane.js` | Text/HTML rendering |
| `panes/ImagePane.js` | Image display with zoom/pan |
| `panes/EmbeddingsPane.js` | t-SNE visualization with D3 lasso |
| `panes/NetworkPane.js` | D3 force-directed graph |
| `panes/PropertiesPane.js` | Interactive form widgets |
| `topbar/` | Connection indicator, env/filter/view controls |
| `modals/` | Environment and view management dialogs |

## Build

- Entry: `js/main.js` → Output: `py/visdom/static/js/main.js`
- Dev build: `npm run dev` (watch mode, source maps)
- Prod build: `npm run build` (minified)
- `@generated` banner added to output — never manually edit compiled files

## Webpack Config

- Polyfills: `stream-browserify`, `browserify-zlib`, `util`, `https-browserify`, `stream-http`, `whatwg-fetch`
- `net` and `dns` set to `false` (browser environment)

## ESLint Config (`.eslintrc`)

- `eslint:recommended` + React + jsx-a11y + Prettier
- Max line length: 80 (URLs and strings exempt)
- Import sorting enforced (`simple-import-sort`)
- No console (warn level)
- `Plotly` declared as readonly global

## Prettier Config (`.prettierrc`)

- `singleQuote`, `semi`, `trailingComma`, `tabWidth` configured explicitly

## CDN Dependencies (downloaded by `build.py`)

Downloaded on first server run to `py/visdom/static/`:
Plotly.js 2.11.1, jQuery 3.1.1, Bootstrap 3.3.7, React 16.2.0, MathJax 2.7.5, D3 v3, SJCL, and others.

> **Note:** Bundled React in `static/` is 16.2.0 for runtime, while webpack-compiled `main.js` uses React 17.0.2 from `node_modules`. Both are loaded in the browser. This is a known legacy setup.

## JavaScript Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `react` / `react-dom` | 17.0.2 | UI framework |
| `react-grid-layout` | 0.16.6 | Draggable/resizable grid |
| `three` | 0.105.2 | 3D rendering |
| `d3-*` | 1.x | Interactions, force layout, lasso |
| `fast-json-patch` | 3.1.1 | Efficient data updates |
| `rc-tree-select` | 1.12.13 | Environment selector |
| `react-modal` | 3.16.1 | Modal dialogs |
| `jquery` | 3.6.3 | DOM manipulation |

## Dev Dependencies

| Package | Purpose |
|---------|---------|
| `webpack` 5.x | Module bundler |
| `babel-loader` | Transpilation |
| `eslint` + plugins | Code quality |
| `prettier` | Formatting |
| `cypress` 9.7.0 | E2E testing |
| `pixelmatch` / `pngjs` | Visual regression |
