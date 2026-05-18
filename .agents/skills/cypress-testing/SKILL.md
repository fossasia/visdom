---
name: cypress-testing
description: Cypress test creation, visual regression workflow, and testing best practices for Visdom
---

# Skill: Cypress Testing

## When to Use

Use this skill when writing new Cypress tests, running visual regression tests, or debugging test failures.

## Core Workflow

1. Start a fresh test server:
   ```bash
   visdom -port 8098 -env_path /tmp
   ```

2. Generate baseline screenshots (first time or after UI changes):
   ```bash
   npm run test:init
   ```

3. Run tests:
   ```bash
   npm run test           # All tests (CLI)
   npm run test:gui       # Interactive GUI
   npm run test:visual    # Visual regression only
   ```

## Writing Tests

- Place test files in `cypress/integration/`
- Follow existing patterns from `basic.js`, `pane.js`, `text.js`
- Visual regression uses `pixelmatch` in `cypress/plugins/`
- Tests connect to server on port `8098`

## CI Behavior

- Functional tests run on Python 3.8, 3.9, 3.10
- Tests run in both WebSocket and polling modes
- Visual regression compares PR screenshots against base branch baseline

## Guardrails

- Always use port `8098` and `-env_path /tmp` for test isolation
- Run `test:init` before `test:visual` to establish baselines
- If visual tests fail, compare screenshots manually — may be font/timing differences
- Run `python example/demo.py` on your branch and clean branch to verify no regressions
