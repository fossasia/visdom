# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import numpy as np


def plot_pointcloud_basic(viz, env, args):
    title = args[0] if len(args) > 0 else "Point cloud"
    n = int(args[1]) if len(args) > 1 else 100_000
    xyz = np.random.randn(n, 3).astype(np.float32)
    return viz.pointcloud3d(
        xyz,
        env=env,
        opts=dict(title=title + " ({} pts)".format(n), markersize=2, show_axes=True),
    )


def plot_pointcloud_rgb(viz, env, args):
    title = args[0] if len(args) > 0 else "RGB cloud"
    n = int(args[1]) if len(args) > 1 else 100_000
    xyz = np.random.randn(n, 3).astype(np.float32)
    rgb = np.random.randint(0, 256, size=(n, 3), dtype=np.uint8)
    return viz.pointcloud3d(
        xyz,
        rgb=rgb,
        env=env,
        opts=dict(
            title=title + " ({} pts, downsampled to 50,000)".format(n),
            markersize=2,
            max_points=50_000,
            downsample="stride",
        ),
    )
