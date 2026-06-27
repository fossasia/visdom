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
