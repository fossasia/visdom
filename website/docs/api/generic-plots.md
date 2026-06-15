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
