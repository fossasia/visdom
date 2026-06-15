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

> The `visdom` command is equivalent to running `python -m visdom.server`.

> If the above does not work, try using an SSH tunnel to your server by adding the following line to your local `~/.ssh/config`:
> ```
> LocalForward 127.0.0.1:8097 127.0.0.1:8097
> ```

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
