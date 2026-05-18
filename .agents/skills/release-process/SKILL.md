---
name: release-process
description: Version bumping, release workflow, and PyPI publishing process for Visdom
---

# Skill: Release Process

## When to Use

Use this skill when preparing a new release or updating the version.

## Core Workflow

1. Update version in `py/visdom/VERSION` following [Semantic Versioning](https://semver.org/).

2. Ensure all CI checks pass:
   - `npm run lint` (JavaScript)
   - `black py` (Python)
   - `pre-commit run --all-files`
   - Cypress tests pass

3. Submit PR to `master` with version change.

4. On merge to `master`, automated workflows handle:
   - **`update-js-build-files.yml`**: Compiles `main.js` if `js/**` changed
   - **`pypi.yml`**: Creates GitHub release (`v<VERSION>`) and publishes to PyPI

## Version Details

- Version stored as single-line plaintext in `py/visdom/VERSION`
- `setup.py` reads this file at build time
- `build.py` uses version to track CDN dependency freshness
- PyPI build uses `python setup.py sdist`

## Guardrails

- Follow Semantic Versioning strictly
- Never manually commit compiled JS files — let the CI workflow handle it
- Ensure `demo.py` runs cleanly before releasing
- Do not push directly to `master`
