---
sidebar_position: 4
title: Generic Plots
description: Create arbitrary Plotly visualizations with the raw API
---

# Generic Plots

The server API adheres to the Plotly convention of `data` and `layout` objects, such that you can produce your own arbitrary Plotly visualizations:

```python
import visdom
vis = visdom.Visdom()

trace = dict(
    x=[1, 2, 3],
    y=[4, 5, 6],
    mode="markers+lines",
    type='custom',
    marker={'color': 'red', 'symbol': 104, 'size': "10"},
    text=["one", "two", "three"],
    name='1st Trace',
)
layout = dict(
    title="First Plot",
    xaxis={'title': 'x1'},
    yaxis={'title': 'x2'},
)

vis._send({'data': [trace], 'layout': layout, 'win': 'mywin'})
```

This gives you full control over the Plotly trace and layout configuration. Refer to the [Plotly JavaScript reference](https://plotly.com/javascript/) for all available options.

## Multiple Traces

You can combine multiple traces in a single plot:

```python
import numpy as np

x = np.linspace(0, 10, 100).tolist()
trace1 = dict(
    x=x,
    y=np.sin(x).tolist(),
    mode='lines',
    type='custom',
    name='sin(x)',
    line={'color': '#1f77b4'},
)
trace2 = dict(
    x=x,
    y=np.cos(x).tolist(),
    mode='lines',
    type='custom',
    name='cos(x)',
    line={'color': '#ff7f0e', 'dash': 'dash'},
)

layout = dict(
    title='Multiple Traces',
    xaxis={'title': 'x'},
    yaxis={'title': 'y'},
)

vis._send({'data': [trace1, trace2], 'layout': layout, 'win': 'multi'})
```

## Layout Customization

You can pass any valid [Plotly layout](https://plotly.com/javascript/reference/layout/) options:

```python
layout = dict(
    title='Customized Layout',
    xaxis=dict(
        title='X Axis',
        showgrid=True,
        zeroline=True,
        range=[0, 10],
    ),
    yaxis=dict(
        title='Y Axis',
        showgrid=True,
        zeroline=True,
    ),
    margin=dict(l=60, r=30, t=50, b=50),
    showlegend=True,
    legend=dict(x=0.8, y=1),
    plot_bgcolor='rgba(240,240,240,0.95)',
)
```

## Common Trace Types

| Type | Description | Key Properties |
|------|-------------|----------------|
| `scatter` | Points and/or lines | `x`, `y`, `mode` (`markers`, `lines`, `markers+lines`) |
| `bar` | Bar chart | `x`, `y`, `orientation` (`v` or `h`) |
| `heatmap` | 2D matrix | `z`, `x`, `y`, `colorscale` |
| `surface` | 3D surface | `z`, `x`, `y`, `colorscale` |
| `pie` | Pie chart | `labels`, `values` |
| `histogram` | Distribution | `x`, `nbinsx` |

:::note
When using the generic API, set `type='custom'` for scatter-like traces. For other trace types, use the Plotly type name directly (e.g. `type='bar'`).
:::
