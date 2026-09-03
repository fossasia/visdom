---
sidebar_position: 10
title: Contributing
description: How to contribute to the Visdom project
---

# Contributing to Visdom

We want to make contributing to this project as easy and transparent as possible.

## Pull Requests

We actively welcome your pull requests.

1. Fork the repo and create your branch from `master`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. If you change `js/`, commit the React-compiled version of `main.js`. For details, see "Contributing to the UI" below.
5. Add demos for new features. Ensure the demos work.
6. Make sure your code lints.
   - For JavaScript files, use `npm lint`
   - For Python files, use `black py` (`pip install black==23.1`)
   - To do that automatically before each `git commit`, enable pre-commit hooks: `pre-commit install`.
7. If you haven't already, complete the Contributor License Agreement ("CLA").

## Contributing to the UI

The UI is built with [React](https://facebook.github.io/react/). For testing, this means that `js/` needs to be compiled. This can be done with `yarn` or `npm`.

For Pull Requests, please let the GitHub Action "Update Static JS Files" compile the file to ensure a consistent build. The GitHub Action is triggered for changed JS files on any branch that you create.

### Building with yarn

```bash
cd /path/to/visdom
yarn             # install node dependencies
yarn run build   # build js
```

### Building with npm

```bash
cd /path/to/visdom
npm install       # install node dependencies
npm run build     # build js
```

## Testing Your Changes

This project uses Playwright for end-to-end and visual regression tests so you
can check for side effects of your changes.

### Using the Playwright UI

1. Run `npx playwright install chromium` on first setup
2. Run `npm run build` or `npm run dev` to compile the frontend
3. Make sure port `8098` is available; Playwright starts an isolated Visdom
   server automatically
4. Run `npm run test:gui`

### As CLI Tests

1. Run `npx playwright install chromium` on first setup
2. Run `npm run build` or `npm run dev`
3. Run the WebSocket suite with `npm test`
4. Run the polling suite with `npm run test:polling`
5. For visual changes, generate baselines before editing with
   `npm run test:init`, then compare with `npm run test:visual`

## Local Development

Install from source for development:

```bash
pip uninstall visdom && pip install -e .
```

:::note
Running `python -m visdom.server` may still import an already installed `visdom` package from `site-packages` instead of the checked-out repository source. To verify:
```bash
python -c "import visdom; print(visdom.__file__)"
```
If needed, prioritize the local source:
```bash
export PYTHONPATH=$PWD/py:$PYTHONPATH
```
:::

## Coding Style

- Follow PEP 8 for Python
- 80 character line length

## How to Report an Issue

Include the following information in your bug report:

1. The error message produced by the visdom server (if any)
2. The error message produced by the JavaScript Console (if any). In Chrome, click View > Developer > JavaScript Console.
3. The platform that you're running on (OS, browser, visdom version)

## License

By contributing to Visdom, you agree that your contributions will be licensed under the LICENSE file in the root directory of this source tree.
