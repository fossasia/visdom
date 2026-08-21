<!-- Copyright 2017-present, The Visdom Authors
     All rights reserved.

     This source code is licensed under the license found in the
     LICENSE file in the root directory of this source tree. -->

# Manual checks

Scripts here drive a **running** visdom server and are judged by looking at the
browser. They are not tests: pytest does not collect them (`testpaths` is
`py/tests`), and nothing in CI runs them.

Automated checks belong elsewhere:

| Question | Where it is answered |
|---|---|
| Does the server behave correctly? | `py/tests/` (pytest) |
| Does the UI still render the same pixels? | `playwright/`, `cypress/` |
| Does this *look* right to a person? | here |

## `visual_check.py`

Creates one window of each visualization type in the `visual_check` environment,
then prints a checklist to walk through in the browser. Useful after a
dependency bump or a change to the plotting payloads.

```bash
visdom -port 8097 -env_path /tmp     # in one shell
python example/manual/visual_check.py
# then open http://localhost:8097/env/visual_check
```
