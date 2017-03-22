# Copyright 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from visdom import Visdom
import numpy as np
import math

viz = Visdom()

textwindow = viz.text('Hello World!')

viz.image(
    np.random.rand(512, 256, 3),
    opts=dict(title='Random!', caption='How random.'),
)

# scatter plots
Y = np.random.rand(100)
viz.scatter(
    X=np.random.rand(100, 2),
    Y=(Y[Y > 0] + 1.5).astype(int),
    opts=dict(
        legend=['Apples', 'Pears'],
        xtickmin=-5,
        xtickmax=5,
        xtickstep=0.5,
        ytickmin=-5,
        ytickmax=5,
        ytickstep=0.5,
        markersymbol='cross-thin-open',
    ),
)

viz.scatter(
    X=np.random.rand(100, 3),
    Y=(Y + 1.5).astype(int),
    opts=dict(
        legend=['Men', 'Women'],
        markersize=5,
    )
)

# 2D scatterplot with custom intensities (red channel)
viz.scatter(
    X=np.random.rand(255, 2),
    Y=(np.random.rand(255) + 1.5).astype(int),
    opts=dict(
        markersize=10,
        markercolor=np.random.randint(0, 255, (2, 3,)),
    ),
)

# 2D scatter plot with custom colors per label:
viz.scatter(
    X=np.random.rand(255, 2),
    Y=(np.random.randn(255) > 0) + 1,
    opts=dict(
        markersize=10,
        markercolor=np.floor(np.random.random((2, 3)) * 255),
    ),
)

win = viz.scatter(
    X=np.random.rand(255, 2),
    opts=dict(
        markersize=10,
        markercolor=np.random.randint(0, 255, (255, 3,)),
    ),
)

# add new trace to scatter plot
viz.updateTrace(
    X=np.random.rand(255),
    Y=np.random.rand(255),
    win=win,
    name='new_trace',
)


# bar plots
viz.bar(X=np.random.rand(20))
viz.bar(
    X=np.abs(np.random.rand(5, 3)),
    opts=dict(
        stacked=True,
        legend=['Facebook', 'Google', 'Twitter'],
        rownames=['2012', '2013', '2014', '2015', '2016']
    )
)
viz.bar(
    X=np.random.rand(20, 3),
    opts=dict(
        stacked=False,
        legend=['The Netherlands', 'France', 'United States']
    )
)

# histogram
viz.histogram(X=np.random.rand(10000), opts=dict(numbins=20))

# heatmap
viz.heatmap(
    X=np.outer(np.arange(1, 6), np.arange(1, 11)),
    opts=dict(
        columnnames=['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'],
        rownames=['y1', 'y2', 'y3', 'y4', 'y5'],
        colormap='Electric',
    )
)

# contour
x = np.tile(np.arange(1, 101), (100, 1))
y = x.transpose()
X = np.exp((((x - 50) ** 2) + ((y - 50) ** 2)) / -(20.0 ** 2))
viz.contour(X=X, opts=dict(colormap='Viridis'))

# surface
viz.surf(X=X, opts=dict(colormap='Hot'))

# line plots
viz.line(Y=np.random.rand(10))

Y = np.linspace(-5, 5, 100)
viz.line(
    Y=np.column_stack((Y * Y, np.sqrt(Y + 5))),
    X=np.column_stack((Y, Y)),
    opts=dict(markers=False),
)

# line updates
win = viz.line(
    X=np.column_stack((np.arange(0, 10), np.arange(0, 10))),
    Y=np.column_stack((np.linspace(5, 10, 10), np.linspace(5, 10, 10) + 5)),
)
viz.line(
    X=np.column_stack((np.arange(10, 20), np.arange(10, 20))),
    Y=np.column_stack((np.linspace(5, 10, 10), np.linspace(5, 10, 10) + 5)),
    win=win,
    update='append'
)
viz.updateTrace(
    X=np.arange(21, 30),
    Y=np.arange(1, 10),
    win=win,
    name='2'
)
viz.updateTrace(
    X=np.arange(1, 10),
    Y=np.arange(11, 20),
    win=win,
    name='4'
)

Y = np.linspace(0, 4, 200)
win = viz.line(
    Y=np.column_stack((np.sqrt(Y), np.sqrt(Y) + 2)),
    X=np.column_stack((Y, Y)),
    opts=dict(
        fillarea=True,
        legend=False,
        width=400,
        height=400,
        xlabel='Time',
        ylabel='Volume',
        ytype='log',
        title='Stacked area plot',
        marginleft=30,
        marginright=30,
        marginbottom=80,
        margintop=30,
    ),
)

# boxplot
X = np.random.rand(100, 2)
X[:, 1] += 2
viz.boxplot(
    X=X,
    opts=dict(legend=['Men', 'Women'])
)

# stemplot
Y = np.linspace(0, 2 * math.pi, 70)
X = np.column_stack((np.sin(Y), np.cos(Y)))
viz.stem(
    X=X,
    Y=Y,
    opts=dict(legend=['Sine', 'Cosine'])
)

# pie chart
X = np.asarray([19, 26, 55])
viz.pie(
    X=X,
    opts=dict(legend=['Residential', 'Non-Residential', 'Utility'])
)

# SVG plotting
svgstr = """
<svg height="300" width="300">
  <ellipse cx="80" cy="80" rx="50" ry="30"
   style="fill:red;stroke:purple;stroke-width:2" />
  Sorry, your browser does not support inline SVG.
</svg>
"""
viz.svg(
    svgstr=svgstr,
    opts=dict(title='Example of SVG Rendering')
)

# close text window:
viz.close(win=textwindow)
