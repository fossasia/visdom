---
sidebar_position: 3
title: Command Line Options
description: Server command line options and configuration
---

# Command Line Options

The following options can be provided to the server:

| Option | Description |
|--------|-------------|
| `-port` | The port to run the server on |
| `-hostname` | The hostname to run the server on |
| `-base_url` | The base server url (default = `/`) |
| `-env_path` | The path to the serialized session to reload |
| `-logging_level` | Logging level (default = INFO). Accepts both standard text and numeric logging values |
| `-readonly` | Flag to start server in readonly mode |
| `-enable_login` | Flag to setup authentication for the server, requiring a username and password to login |
| `-force_new_cookie` | Flag to reset the secure cookie used by the server, invalidating current login cookies. Requires `-enable_login` |
| `-bind_local` | Flag to make the server accessible only from localhost |
| `-eager_data_loading` | By default visdom loads environments lazily upon user request. Setting this flag lets visdom pre-fetch all environments upon startup |
| `-save_interval` | Seconds between automatic saves of changed environments (default = 30). Set to 0 to disable the timer |
| `-save_threshold` | Save an environment early once it has taken this many updates (default = 50), so a busy one is not left unsaved for a whole interval. Set to 0 to disable |

## Saving

Environments are held in memory and written to `-env_path` automatically: every
`-save_interval` seconds, and immediately once an environment has taken
`-save_threshold` updates. Only environments that changed since the last write are
saved. The write runs on a background storage thread, so a large environment
reaching disk does not hold up the requests arriving while it is written.

Setting both to 0 restores the older behaviour of saving only when asked, and once
more at shutdown.

### Stopping the server

`Ctrl-C` or `docker stop` (`SIGTERM`) shuts down in order: the listening socket
closes, queued writes finish, and every changed environment is saved before the
process exits. Nothing you plotted is lost by stopping the server normally, so
there is no need to call `vis.save()` first. A `SIGKILL` still cannot be caught,
and loses whatever the last autosave did not cover.

## Authentication

:::danger Security
By default, Visdom runs **without authentication**. Anyone who can reach the server can view and modify your environments. For any shared or production deployment, always use `-enable_login` and `-bind_local`:

```bash
visdom -enable_login -bind_local
```
:::

When the `-enable_login` flag is provided, the server asks user to input credentials using terminal prompt. Alternatively, you can setup environment variables for non-interactive login:

```bash
VISDOM_USERNAME=<your-username>
VISDOM_PASSWORD=<your-password>
VISDOM_USE_ENV_CREDENTIALS=1 visdom -enable_login
```

:::warning
Never hardcode real credentials in scripts or commit them to version control. Use a secrets manager or environment variables set outside your codebase.
:::

This setup is useful when launching `visdom` server from a bash script or from a Jupyter notebook.

You can also use the `VISDOM_COOKIE` variable to provide cookies value if the cookie file wasn't generated, or the flag `-force_new_cookie` was set.
