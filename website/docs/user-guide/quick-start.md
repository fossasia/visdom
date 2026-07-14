---
sidebar_position: 1
title: Quick Start
description: Get up and running with Visdom in under 5 minutes
---

# Quick Start

This guide walks you through installing Visdom, starting the server, and creating your first visualizations.

## 1. Install Visdom

```bash
pip install visdom
```

## 2. Start the server

```bash
visdom
```

You should see output like:

```
Checking for scripts.
It's Alive!
INFO:root:Application Started
You can navigate to http://localhost:8097
```

## 3. Open the dashboard

Navigate to **http://localhost:8097** in your browser. You will see an empty dashboard:

![Visdom Dashboard](https://user-images.githubusercontent.com/19650074/198747904-7a8a580f-851a-45fb-8f45-94e54a910ee2.png)

## 4. Create your first visualization

Open a Python shell or script and run:

```python
import visdom
import numpy as np

vis = visdom.Visdom()

# Check that the server is connected
assert vis.check_connection(timeout_seconds=3), \
    "Visdom server is not running at http://localhost:8097"

# 1. Display some text
vis.text('<h2>Hello Visdom!</h2><p>Your first visualization.</p>',
         win='hello', opts=dict(title='Welcome'))

# 2. Show a random image
vis.image(np.random.rand(3, 256, 256),
          win='random_img', opts=dict(title='Random Image'))

# 3. Plot a sine wave
x = np.linspace(0, 4 * np.pi, 200)
vis.line(Y=np.sin(x), X=x,
         win='sine', opts=dict(title='Sine Wave', xlabel='x', ylabel='sin(x)'))

# 4. Create a scatter plot
vis.scatter(
    X=np.random.rand(100, 2),
    Y=(np.random.rand(100) > 0.5).astype(int) + 1,
    win='scatter',
    opts=dict(title='Random Scatter', legend=['Class A', 'Class B'], markersize=8),
)

# 5. Draw a bar chart
vis.bar(
    X=np.random.rand(5),
    win='bar',
    opts=dict(title='Bar Chart', rownames=['Mon', 'Tue', 'Wed', 'Thu', 'Fri']),
)
```

Switch back to your browser — you should see five windows with your visualizations. You can **drag** them around, **resize** them, and **download** their contents.

<div style={{display: 'flex', gap: '1%'}}>
  <img width="49.5%" src="https://user-images.githubusercontent.com/19650074/198748177-c973f387-c392-4f6e-9e3d-27dfe578eb59.gif" alt="Visdom Interactive Demo" />
  <img width="49.5%" src="https://user-images.githubusercontent.com/19650074/198748189-917091b6-95c4-4415-b965-ba3e7e81e1f8.png" alt="Visdom Plots" />
</div>

## 5. Update a plot in real time

Visdom's `update='append'` lets you stream data to an existing window:

```python
import time

win = vis.line(Y=[0.9], X=[1], opts=dict(title='Training Loss', xlabel='Epoch', ylabel='Loss'))

for epoch in range(2, 50):
    loss = 0.9 * np.exp(-0.05 * epoch) + np.random.normal(0, 0.02)
    vis.line(Y=[loss], X=[epoch], win=win, update='append')
    time.sleep(0.1)
```

Watch the loss curve grow in real time in your browser.

## What's next?

- [Creating Visualizations](./creating-visualizations.md) — all the plot types and media you can display
- [Managing Environments](./environments.md) — organize your work into separate workspaces
- [Live Updates & Streaming](./live-updates.md) — stream data from training loops
- [Full API Reference](/api/overview) — every function and parameter
