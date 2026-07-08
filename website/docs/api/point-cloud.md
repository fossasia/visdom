---
sidebar_position: 7
title: 3D Point Cloud
description: Render interactive 3D point clouds with WebGL
---

# 3D Point Cloud

```python
vis.pointcloud3d(xyz, rgb=None, win=None, env=None, opts=dict())
```

This function renders a 3D point cloud in a dedicated WebGL pane (backed by [Three.js](https://threejs.org/)) with interactive orbit, pan, and zoom controls. It takes as input an `Nx3` tensor `xyz` that specifies the coordinates of the `N` points, and an optional `Nx3` tensor `rgb` containing per-point colors, accepted as integers in `[0, 255]`, floats in `[0, 1]`, or floats in `[0, 255]`.

Interact with the rendered pane using the mouse: left-drag to rotate, scroll to zoom, shift-drag to pan, and double-click to reset the camera.

## Example

```python
import numpy as np

n = 100_000
xyz = np.random.randn(n, 3).astype(np.float32)
rgb = np.random.randint(0, 256, size=(n, 3), dtype=np.uint8)

vis.pointcloud3d(
    xyz,
    rgb=rgb,
    opts=dict(
        title='Random point cloud',
        markersize=2,
        show_axes=True,
    ),
)
```

## Arguments

| Argument | Description |
|----------|-------------|
| `xyz` | `Nx3` array-like of point coordinates |
| `rgb` | Optional `Nx3` array-like of per-point colors, in `[0, 255]` (int), `[0, 1]` (float), or `[0, 255]` (float) |

## Supported Options

| Option | Default | Description |
|--------|---------|-------------|
| `opts.markersize` | `2.0` | Size of the rendered points |
| `opts.opacity` | `1.0` | Opacity of the points, between 0 and 1 |
| `opts.bgcolor` | `'#ffffff'` | CSS background color string for the pane |
| `opts.show_axes` | `true` | Whether to show the XYZ axes |
| `opts.default_color` | `[40, 40, 40]` | `[R, G, B]` (0-255) fallback color used when `rgb` is not provided |
| `opts.max_points` | `None` | If set, downsamples to at most this many points before rendering (hard maximum of 500,000 points) |
| `opts.downsample` | `'stride'` | Downsampling strategy when `max_points` is set: `'stride'` (evenly spaced) or `'random'` |
| `opts.seed` | `None` | Random seed used when `opts.downsample='random'` |
