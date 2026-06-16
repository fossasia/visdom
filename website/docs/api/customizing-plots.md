---
sidebar_position: 5
title: Customizing Plots
description: Generic plot options available for all visualization types
---

# Customizing Plots

The plotting functions take an optional `opts` table as input that can be used to change (generic or plot-specific) properties of the plots.

All input arguments are specified in a single table; the input arguments are matched based on the keys they have in the input table.

## Passing Options

`opts` are passed as dictionary in Python scripts:

```python
opts = dict(title="my title", xlabel="x axis", ylabel="y axis")
```

or:

```python
opts = {"title": "my title", "xlabel": "x axis", "ylabel": "y axis"}
```

## Generic Options

The following `opts` are generic in the sense that they are the same for all visualizations (except `plot.image`, `plot.text`, `plot.video`, and `plot.audio`):

| Option | Description |
|--------|-------------|
| `opts.title` | Figure title |
| `opts.width` | Figure width |
| `opts.height` | Figure height |
| `opts.showlegend` | Show legend (`true` or `false`) |
| `opts.xtype` | Type of x-axis (`'linear'` or `'log'`) |
| `opts.xlabel` | Label of x-axis |
| `opts.xtick` | Show ticks on x-axis (`boolean`) |
| `opts.xtickmin` | First tick on x-axis (`number`) |
| `opts.xtickmax` | Last tick on x-axis (`number`) |
| `opts.xtickvals` | Locations of ticks on x-axis (`table` of `number`s) |
| `opts.xticklabels` | Tick labels on x-axis (`table` of `string`s) |
| `opts.xtickstep` | Distances between ticks on x-axis (`number`) |
| `opts.xtickfont` | Font for x-axis labels (dict of [font information](https://plot.ly/javascript/reference/#layout-font)) |
| `opts.ytype` | Type of y-axis (`'linear'` or `'log'`) |
| `opts.ylabel` | Label of y-axis |
| `opts.ytick` | Show ticks on y-axis (`boolean`) |
| `opts.ytickmin` | First tick on y-axis (`number`) |
| `opts.ytickmax` | Last tick on y-axis (`number`) |
| `opts.ytickvals` | Locations of ticks on y-axis (`table` of `number`s) |
| `opts.yticklabels` | Tick labels on y-axis (`table` of `string`s) |
| `opts.ytickstep` | Distances between ticks on y-axis (`number`) |
| `opts.ytickfont` | Font for y-axis labels (dict of [font information](https://plot.ly/javascript/reference/#layout-font)) |
| `opts.marginleft` | Left margin (in pixels) |
| `opts.marginright` | Right margin (in pixels) |
| `opts.margintop` | Top margin (in pixels) |
| `opts.marginbottom` | Bottom margin (in pixels) |

The other options are visualization-specific, and are described in the documentation of the individual functions.

## Practical Examples

### Customizing axis labels and title

```python
vis.line(
    Y=data,
    X=steps,
    opts=dict(
        title='Training Loss over Time',
        xlabel='Epoch',
        ylabel='Loss',
        showlegend=True,
        legend=['Train', 'Validation'],
    ),
)
```

### Using log scale

```python
vis.line(
    Y=loss_values,
    X=steps,
    opts=dict(
        title='Loss (log scale)',
        ytype='log',
        ylabel='Loss',
        xlabel='Step',
    ),
)
```

### Custom margins and size

```python
vis.bar(
    X=values,
    opts=dict(
        title='Wide Chart',
        width=800,
        height=400,
        marginbottom=80,
        rownames=long_labels,
    ),
)
```

### Using layoutopts for advanced Plotly configuration

Many plotting functions accept `opts.layoutopts`, which is passed directly to Plotly's layout configuration:

```python
vis.line(
    Y=data,
    X=x,
    opts=dict(
        title='Advanced Layout',
        layoutopts=dict(
            plot_bgcolor='rgba(240,240,240,0.95)',
            xaxis=dict(gridcolor='white'),
            yaxis=dict(gridcolor='white'),
        ),
    ),
)
```
