---
sidebar_position: 7
title: Sharing & Security
description: Share visualizations with collaborators and secure your server
---

# Sharing & Security

Visdom is designed for collaborative visualization. You can share environments via URL, set up authentication, and control access.

## Sharing via URL

Every environment is accessible at a unique URL:

```
http://<your-server>:8097/env/<environment_name>
```

Share this URL with collaborators to give them read/write access to that environment. Anyone who can reach the server can view and modify it.

## Authentication

By default, Visdom runs **without authentication**. For any shared or production deployment, enable login:

```bash
visdom -enable_login
```

The server will prompt you for a username and password on first launch.

### Non-interactive login

Set credentials via environment variables for automated or headless setups:

```bash
export VISDOM_USERNAME=myuser
export VISDOM_PASSWORD=mypass
export VISDOM_USE_ENV_CREDENTIALS=1
visdom -enable_login
```

:::warning
Never hardcode credentials in scripts or commit them to version control. Use a secrets manager or environment variables set outside your codebase.
:::

### Connecting with credentials

```python
vis = visdom.Visdom(
    server='http://my-server',
    port=8097,
    username='myuser',
    password='mypass',
)
```

## Binding to localhost

To prevent access from other machines on the network:

```bash
visdom -enable_login -bind_local
```

With `-bind_local`, the server only accepts connections from `127.0.0.1`. Use an SSH tunnel for remote access:

```
# In your local ~/.ssh/config
Host myserver
    HostName remote-machine.example.com
    LocalForward 127.0.0.1:8097 127.0.0.1:8097
```

Then connect via `ssh myserver` and access `http://localhost:8097` locally.

## Cookie management

Visdom uses secure cookies for authenticated sessions. If you need to reset cookies:

```bash
visdom -enable_login -force_new_cookie
```

You can also provide cookies programmatically:

```bash
export VISDOM_COOKIE=<cookie_value>
```

## Read-only mode

Start the server in read-only mode to prevent modifications:

```bash
visdom -readonly
```

In read-only mode, users can view environments but cannot create, modify, or delete visualizations.

## Using a reverse proxy

For production deployments, place Visdom behind a reverse proxy (e.g., Nginx) with HTTPS:

```nginx
server {
    listen 443 ssl;
    server_name visdom.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8097;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

:::note
The `Upgrade` and `Connection` headers are required for WebSocket support, which Visdom uses for real-time updates and callbacks.
:::

## Custom base URL

If Visdom is served under a subpath:

```bash
visdom -base_url /visdom/
```

Then access at `http://your-server/visdom/`.
