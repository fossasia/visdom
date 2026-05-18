# Skills Directory Guide

This directory stores reusable operational skills for agents.

## Skill Layout

Each skill directory follows a consistent scaffold:

```text
skill-name/
├── SKILL.md            # Required: metadata + instructions
├── references/         # Reference notes and default test format
│   ├── REFERENCE.md
│   └── TESTS.md
├── assets/             # Optional templates/resources
│   └── README.md
└── ...
```

Default scaffold templates are stored in `_defaults/` as:

- `_defaults/REFERENCE.md` -> copied to each skill's `references/REFERENCE.md`
- `_defaults/TESTS.md` -> copied to each skill's `references/TESTS.md`
- `_defaults/ASSETS.md` -> copied to each skill's `assets/README.md`

## Available Skills

- **adding-pane** — Step-by-step guide for adding a new visualization pane type
- **websocket-flow** — Guide for adding new WebSocket commands and API endpoints
- **cypress-testing** — Cypress test creation and visual regression workflow
- **release-process** — Version bumping and release workflow
- **python-client-api** — Add or modify Python client methods with type/server parity
- **handler-auth-flow** — Safely change handlers and auth-gated endpoints
- **environment-views** — Manage env lifecycle, compare mode, and views
- **callback-events** — Browser-to-Python callback routing and event contracts
- **update-patching** — Incremental update and jsonpatch behavior
- **auth-login** — Login, cookie, and auth-path correctness
- **offline-replay** — Offline logging and replay flows
- **performance-streaming** — High-throughput update performance and batching
- **docs-sync** — Keep docs and API examples aligned
- **polling-parity** — Ensure parity between WebSocket and polling modes
- **frontend-pane-lifecycle** — Pane rendering and interaction lifecycle
- **env-persistence** — Environment serialization and reload compatibility
- **ci-workflow-debug** — Diagnose and fix GitHub Actions failures
