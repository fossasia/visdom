# Default Test Format

Use this validation flow unless the skill requires a narrower scope:

1. Start isolated server:
   - `visdom -port 8098 -env_path /tmp`
2. Refresh visual baselines when UI output changes:
   - `npm run test:init`
3. Run standard checks:
   - `npm run test`
   - `npm run lint`
   - `black --check py`
   - `black --check <skill-specific-python-path>` (if the skill adds Python files outside `py/`)
