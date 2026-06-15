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

## Python Example

```python
import visdom
import numpy as np

vis = visdom.Visdom()
vis.text('Hello, world!')
vis.image(np.ones((3, 10, 10)))
```

## Demos

If you have cloned the repository, you can run the demo showcase:

```bash
python example/demo.py
```
