---
sidebar_position: 1
title: API Overview
description: Overview of the Visdom Python API
---

# API Overview

For a quick introduction into the capabilities of `visdom`, have a look at the `example` directory, or read the details below.

## Quick Example

```python
import visdom
import numpy as np

vis = visdom.Visdom()

# Text
vis.text('Hello Visdom!')

# Image
vis.image(np.random.rand(3, 256, 256), opts=dict(title='Random Image'))

# Line plot
X = np.linspace(0, 2 * np.pi, 100)
vis.line(
    Y=np.column_stack([np.sin(X), np.cos(X)]),
    X=X,
    opts=dict(title='Sine & Cosine', legend=['sin', 'cos']),
)

# Scatter plot
vis.scatter(
    X=np.random.rand(100, 2),
    opts=dict(title='Random Scatter', markersize=5),
)

# Bar chart
vis.bar(X=np.random.rand(5), opts=dict(rownames=['A', 'B', 'C', 'D', 'E']))

# Save the environment
vis.save(['main'])
```

## Visdom Arguments (Python only)

The python Visdom client takes the following options:

| Argument | Default | Description |
|----------|---------|-------------|
| `server` | `'http://localhost'` | The hostname of your visdom server |
| `port` | `8097` | The port for your visdom server |
| `base_url` | `/` | The base visdom server url |
| `env` | `'main'` | Default environment to plot to when no `env` is provided |
| `raise_exceptions` | `True` (soon) | Raise exceptions upon failure rather than printing them |
| `log_to_filename` | `None` | If not none, log all plotting and updating events to the given file (append mode) so that they can be replayed later using `replay_log` |
| `use_incoming_socket` | `True` | Enable use of the socket for receiving events from the web client, allowing user to register callbacks |
| `username` | `None` | Username for authentication, if server started with `-enable_login` |
| `password` | `None` | Password for authentication, if server started with `-enable_login` |
| `proxies` | `None` | Dictionary mapping protocol to the URL of the proxy (e.g. `{'http': 'foo.bar:3128'}`) |
| `offline` | `False` | Run visdom in offline mode, where all requests are logged to file rather than to the server. Requires `log_to_filename` is set |

## Basics

Visdom offers the following basic visualization functions:

- [`vis.image`](./basics.md#visimage) — image
- [`vis.images`](./basics.md#visimages) — list of images
- [`vis.text`](./basics.md#vistext) — arbitrary HTML
- [`vis.properties`](./basics.md#visproperties) — properties grid
- [`vis.audio`](./basics.md#visaudio) — audio
- [`vis.video`](./basics.md#visvideo) — videos
- [`vis.svg`](./basics.md#vissvg) — SVG object
- [`vis.matplot`](./basics.md#vismatplot) — matplotlib plot
- [`vis.plotlyplot`](./basics.md#visplotlyplot) — Plotly figure
- [`vis.embeddings`](./basics.md#visembeddings) — t-SNE embeddings
- [`vis.save`](./basics.md#vissave) — serialize state server-side

## Plotting

We have wrapped several common plot types to make creating basic visualizations easy. These visualizations are powered by [Plotly](https://plotly.com/).

- [`vis.scatter`](./plotting.md#visscatter) — 2D or 3D scatter plots
- [`vis.line`](./plotting.md#visline) — line plots
- [`vis.stem`](./plotting.md#visstem) — stem plots
- [`vis.heatmap`](./plotting.md#visheatmap) — heatmap plots
- [`vis.bar`](./plotting.md#visbar) — bar graphs
- [`vis.histogram`](./plotting.md#vishistogram) — histograms
- [`vis.boxplot`](./plotting.md#visboxplot) — boxplots
- [`vis.surf`](./plotting.md#vissurf) — surface plots
- [`vis.contour`](./plotting.md#viscontour) — contour plots
- [`vis.quiver`](./plotting.md#visquiver) — quiver plots
- [`vis.mesh`](./plotting.md#vismesh) — mesh plots
- [`vis.sunburst`](./plotting.md#vissunburst) — sunburst charts
- [`vis.dual_axis_lines`](./plotting.md#visdual_axis_lines) — double y axis line plots

## Generic Plots

See [Generic Plots](./generic-plots.md) for how to produce your own arbitrary Plotly visualizations.

## Others

- [`vis.close`](./other-functions.md#visclose) — close a window by id
- [`vis.delete_env`](./other-functions.md#visdelete_env) — delete an environment by env_id
- [`vis.fork_env`](./other-functions.md#visfork_env) — fork an environment
- [`vis.win_exists`](./other-functions.md#viswin_exists) — check if a window already exists by id
- [`vis.get_env_list`](./other-functions.md#visget_env_list) — get a list of all environments on your server
- [`vis.get_window_data`](./other-functions.md#visget_window_data) — get current data for a window
- [`vis.check_connection`](./other-functions.md#vischeck_connection) — check if the server is connected
- [`vis.replay_log`](./other-functions.md#visreplay_log) — replay the actions from a log file

## Common Patterns

### Updating existing plots

Many plotting functions support an `update` parameter to append or replace data in an existing window:

```python
# Create a plot
win = vis.line(Y=[1], X=[1], opts=dict(title='Live'))

# Append new points
vis.line(Y=[2], X=[2], win=win, update='append')
vis.line(Y=[3], X=[3], win=win, update='append')
```

### Naming windows

Use the `win` parameter to target a specific window. If a window with that id exists, it will be updated:

```python
vis.text('First message', win='my_window')
vis.text('Updated message', win='my_window')  # replaces content
```
