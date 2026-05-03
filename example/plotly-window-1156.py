#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

# Example for PR #1156
# -----------------------------------
# Bug:  vis.plotlyplot() ignored the width and height set in the Plotly
#       figure's layout.  No matter what figure.layout.width / height you
#       specified, the visdom window always opened at the default size.
#
# Fix:  In plotlyplot() the layout dict is now inspected after JSON
#       round-tripping.  If "width" or "height" are present they are
#       forwarded into the opts dict that is sent to the server so the
#       window is created at exactly the dimensions the figure requested:
#
#           if "width" in figure_dict["layout"]:
#               opts["width"] = figure_dict["layout"]["width"]
#           if "height" in figure_dict["layout"]:
#               opts["height"] = figure_dict["layout"]["height"]
#
# Run:  python example/plotly-window-1156.py
# Then: open http://localhost:8097
#
# Produces 2 windows matching the PR #1156 screenshot:
#   1. Default size  – plotly bar chart, no width/height in layout
#                      window opens at the default visdom size
#   2. Custom size   – same bar chart, layout.width=600  layout.height=400
#                      window respects those exact pixel dimensions (the fix)

import numpy as np
import plotly.graph_objects as go
from visdom import Visdom

vis = Visdom()
assert vis.check_connection(timeout_seconds=3), \
    'Start visdom first:  python -m visdom.server'

x = [1, 2, 3]
y = [1, 3, 2]

# ── 1. Default visdom window size (no width/height in plotly layout) ──────────
# Before the fix this was the only outcome even when width/height were set.
print('Creating default-size window...')
fig_default = go.Figure(
    data=go.Bar(x=x, y=y, marker_color='cornflowerblue'),
    layout=go.Layout(
        title='Plotly bar — default window size',
        xaxis=dict(title='x'),
        yaxis=dict(title='y'),
    ),
)
vis.plotlyplot(fig_default)

# ── 2. Custom window size via layout.width / layout.height (the fix) ─────────
# After the fix, plotlyplot() reads width/height from figure_dict["layout"]
# and forwards them to opts so the visdom window is created at the right size.
print('Creating custom-size window...')
fig_custom = go.Figure(
    data=go.Bar(x=x, y=y, marker_color='cornflowerblue'),
    layout=go.Layout(
        title='Plotly bar — custom size (600 × 400)',
        width=600,
        height=400,
        xaxis=dict(title='x'),
        yaxis=dict(title='y'),
    ),
)
vis.plotlyplot(fig_custom)

print()
print('Done. Open http://localhost:8097')
print()
print('2 windows created matching PR #1156 screenshot:')
print('  1. Default size  – no width/height in plotly layout')
print('                     window opens at default visdom dimensions')
print('  2. Custom size   – layout.width=600, layout.height=400')
print('                     window respects those pixel dimensions (the fix)')
print()
print('Before the fix: window 2 also appeared at the default visdom size,')
print('ignoring the width/height set in the Plotly figure layout.')
