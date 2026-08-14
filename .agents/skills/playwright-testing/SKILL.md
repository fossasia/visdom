---
name: playwright-testing
description: Playwright E2E creation, visual regression workflow, and testing best practices for Visdom
---

# Skill: Playwright Testing

## When to Use

Use this skill when writing Playwright tests, running visual regression tests,
or debugging browser-test failures.

## Core Workflow

1. Install Chromium once:
   ```bash
   npx playwright install chromium
   ```

2. Run functional tests:
   ```bash
   npm test
   npm run test:polling
   npm run test:gui
   ```

3. Run visual regression tests:
   ```bash
   npm run test:init
   npm run test:visual
   ```

## Writing Tests

- Place specs in `playwright/tests/`.
- Put shared browser and demo helpers in `playwright/support/`.
- Follow existing patterns from `basic.spec.js`, `pane.spec.js`, and
  `text.spec.js`.
- Use web-first assertions instead of fixed sleeps when possible.
- Tests use port `8098`; the Playwright config starts the Visdom server.

## CI Behavior

- Functional tests run in WebSocket and polling modes.
- WebSocket tests run on the supported Python version matrix.
- Visual regression compares PR screenshots against a base-branch baseline.

## Guardrails

- Keep WebSocket and polling assertions equivalent.
- Make sure port `8098` is free before running tests locally.
- Run `test:init` before `test:visual` to establish baselines.
- If visual tests fail, inspect the generated diff and trace before changing
  thresholds.
- Do not commit generated reports or test results.

## Documentation

- `playwright/`
- `playwright.config.js`
- `playwright.polling.config.js`
- `.github/workflows/`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Tests

- Functional: `npm test` and `npm run test:polling`
- Visual: `npm run test:init` followed by `npm run test:visual`
