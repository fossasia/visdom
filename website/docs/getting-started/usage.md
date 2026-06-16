---
sidebar_position: 2
title: Usage
description: How to start and use the Visdom server
---

# Usage

## Starting the Server

Start the server (probably in a `screen` or `tmux`) from the command line:

```bash
visdom
```

Visdom now can be accessed by going to `http://localhost:8097` in your browser, or your own host address if specified.

:::tip
The `visdom` command is equivalent to running `python -m visdom.server`.
:::

:::caution Remote Access
If accessing a remote server, use an SSH tunnel by adding the following line to your local `~/.ssh/config`:
```
LocalForward 127.0.0.1:8097 127.0.0.1:8097
```
Note that an SSH tunnel alone does not add authentication. If you are on a shared machine, also use `-enable_login` and `-bind_local` to prevent unauthorized access. See [Command Line Options](./command-line-options.md) for details.
:::

## Hello World

Create a simple visualization to verify everything is working:

```python
import visdom
import numpy as np

vis = visdom.Visdom()

# Check the server is connected
assert vis.check_connection(timeout_seconds=3), \
    "Could not connect to Visdom server"

# Display a text window
vis.text('Hello, world!')

# Display a random image
vis.image(np.random.rand(3, 64, 64))

# Plot a sine wave
x = np.linspace(0, 2 * np.pi, 100)
vis.line(Y=np.sin(x), X=x, opts=dict(title='Sine Wave'))
```

## Working with Environments

Environments let you organize visualizations into separate workspaces:

```python
import visdom

# Create a client targeting a specific environment
vis = visdom.Visdom(env='experiment_1')

vis.text('This goes to experiment_1')

# You can also specify env per-call
vis.text('This goes to experiment_2', env='experiment_2')
```

Access a specific environment via URL: `http://localhost:8097/env/experiment_1`

## Using in Jupyter Notebooks

Visdom works in Jupyter notebooks. Start the server in a separate terminal, then use Visdom in your notebook cells:

```python
import visdom
vis = visdom.Visdom()

# All Visdom calls work the same way
vis.text('Hello from Jupyter!')
```

## Offline Mode

You can log all Visdom calls to a file for later replay, without a running server:

```python
import visdom

vis = visdom.Visdom(
    offline=True,
    log_to_filename='visdom_log.json'
)

# All calls are saved to the log file
vis.text('This is logged offline')
vis.line(Y=[1, 2, 3], X=[1, 2, 3])
```

Replay the log when a server is available:

```python
vis_online = visdom.Visdom()
vis_online.replay_log('visdom_log.json')
```

## Demos

If you have cloned the repository, you can run the demo showcase:

```bash
python example/demo.py
```

## Connecting to a Remote Server

To connect to a Visdom server running on a different machine:

```python
vis = visdom.Visdom(server='http://remote-host', port=8097)
```

If the server has authentication enabled:

```python
vis = visdom.Visdom(
    server='http://remote-host',
    port=8097,
    username='myuser',
    password='mypass'
)
```
