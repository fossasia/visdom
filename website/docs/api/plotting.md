---
sidebar_position: 3
title: Plotting
description: Wrapped plotting functions — scatter, line, bar, heatmap, and more
---

# Plotting

Further details on the wrapped plotting functions are given below.

The exact inputs into the plotting functions vary, although most of them take as input a tensor `X` that contains the data and an (optional) tensor `Y` that contains optional data variables (such as labels or timestamps). All plotting functions take as input an optional `win` that can be used to plot into a specific window; each plotting function also returns the `win` of the window it plotted in. One can also specify the `env` to which the visualization should be added.

## vis.scatter

This function draws a 2D or 3D scatter plot. It takes as input an `Nx2` or `Nx3` tensor `X` that specifies the locations of the `N` points in the scatter plot. An optional `N` tensor `Y` containing discrete labels that range between `1` and `K` can be specified as well — the labels will be reflected in the colors of the markers.

`update` can be used to efficiently update the data of an existing plot. Use `'append'` to append data, `'replace'` to use new data, or `'remove'` to remove the trace specified by `name`. Using `update='append'` will create a plot if it doesn't exist and append to the existing plot otherwise. If updating a single trace, use `name` to specify the name of the trace to be updated. Update data that is all NaN is ignored (can be used for masking update).

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.markersymbol` | `'dot'` | Marker symbol (`string`) |
| `opts.markersize` | `'10'` | Marker size (`number`) |
| `opts.markercolor` | `nil` | Color per marker (`torch.*Tensor`) |
| `opts.markerborderwidth` | `0.5` | Marker border line width (`float`) |
| `opts.legend` | — | Table containing legend names |
| `opts.textlabels` | `None` | Text label for each point (`list`) |
| `opts.layoutopts` | — | Dict of additional layout options |
| `opts.traceopts` | — | Dict mapping trace names to additional trace options |
| `opts.webgl` | `false` | Use WebGL for plotting (`boolean`) |

`opts.markercolor` is a Tensor with Integer values. The tensor can be of size `N` or `N x 3` or `K` or `K x 3`:

- **Tensor of size `N`**: Single intensity value per data point. 0 = black, 255 = red
- **Tensor of size `N x 3`**: Red, Green and Blue intensities per data point. 0,0,0 = black, 255,255,255 = white
- **Tensor of size `K` and `K x 3`**: Instead of having a unique color per data point, the same color is shared for all points of a particular label.

## vis.sunburst

This function draws a sunburst chart. It takes two input arrays: `parents` and `labels`. Values from the `parents` array define the hierarchical structure, indicating which parent sector a sector belongs to. Values from the `labels` array define the sector's label or name.

Examples: `vis.sunburst(parents, labels, opts)` or `vis.sunburst(parents, labels, values, opts)`

**Supported opts:**

| Option | Description |
|--------|-------------|
| `opts.font_size` | Define font size of label (`int`) |
| `opts.font_color` | Define font color of label (`string`) |
| `opts.opacity` | Define opacity of chart (`float`) |
| `opts.line_width` | Define distance between sectors (`int`) |

## vis.line

This function draws a line plot. It takes as input an `N` or `NxM` tensor `Y` that specifies the values of the `M` lines (that connect `N` points) to plot. It also takes an optional `X` tensor that specifies the corresponding x-axis values; `X` can be an `N` tensor (in which case all lines will share the same x-axis values) or have the same size as `Y`.

`update` can be used to efficiently update the data of an existing plot. Use `'append'` to append data, `'replace'` to use new data, or `'remove'` to remove the trace specified by `name`.

**Smoothing**: Line plots can be smoothened using [Savitzky-Golay filtering](https://en.wikipedia.org/wiki/Savitzky%E2%80%93Golay_filter). This feature can be enabled by clicking the `~` symbol in the top right corner of a window that contains a line plot.

![Interactive Smoothing Demo](https://user-images.githubusercontent.com/19650074/159366736-1f5d8099-0ea5-4a3b-af17-49d3e24cb32c.gif)

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.fillarea` | — | Fill area below line (`boolean`) |
| `opts.markers` | `false` | Show markers (`boolean`) |
| `opts.markersymbol` | `'dot'` | Marker symbol (`string`) |
| `opts.markersize` | `'10'` | Marker size (`number`) |
| `opts.linecolor` | `None` | Line colors (`np.array`) |
| `opts.dash` | `'solid'` | Line dash type per line (`np.array`): `solid`, `dash`, `dashdot` |
| `opts.legend` | — | Table containing legend names |
| `opts.layoutopts` | — | Dict of additional layout options |
| `opts.traceopts` | — | Dict mapping trace names to additional trace options |
| `opts.webgl` | `false` | Use WebGL for plotting (`boolean`) |

## vis.stem

This function draws a stem plot. It takes as input an `N` or `NxM` tensor `X` that specifies the values of the `N` points in the `M` time series. An optional `N` or `NxM` tensor `Y` containing timestamps can be specified as well.

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.colormap` | `'Viridis'` | Colormap (`string`) |
| `opts.legend` | — | Table containing legend names |
| `opts.layoutopts` | — | Dict of additional layout options |

## vis.heatmap

This function draws a heatmap. It takes as input an `NxM` tensor `X` that specifies the value at each location in the heatmap.

`update` can be used to efficiently update the data: `'appendRow'`, `'appendColumn'`, `'prependRow'`, `'prependColumn'`, `'replace'`, or `'remove'`.

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.colormap` | `'Viridis'` | Colormap (`string`) |
| `opts.xmin` | `X:min()` | Clip minimum value (`number`) |
| `opts.xmax` | `X:max()` | Clip maximum value (`number`) |
| `opts.columnnames` | — | Table containing x-axis labels |
| `opts.rownames` | — | Table containing y-axis labels |
| `opts.layoutopts` | — | Dict of additional layout options |
| `opts.nancolor` | `None` | Color for plotting `NaN`s (`string`) |

## vis.bar

This function draws a regular, stacked, or grouped bar plot. It takes as input an `N` or `NxM` tensor `X` that specifies the height of each bar.

**Supported opts:**

| Option | Description |
|--------|-------------|
| `opts.rownames` | Table containing x-axis labels |
| `opts.stacked` | Stack multiple columns in `X` |
| `opts.legend` | Table containing legend labels |
| `opts.layoutopts` | Dict of additional layout options |

## vis.histogram

This function draws a histogram of the specified data. It takes as input an `N` tensor `X`.

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.numbins` | `30` | Number of bins (`number`) |
| `opts.layoutopts` | — | Dict of additional layout options |

## vis.boxplot

This function draws boxplots. It takes as input an `N` or an `NxM` tensor `X`.

**Supported opts:**

| Option | Description |
|--------|-------------|
| `opts.legend` | Labels for each of the columns in `X` |
| `opts.layoutopts` | Dict of additional layout options |

## vis.surf

This function draws a surface plot. It takes as input an `NxM` tensor `X`.

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.colormap` | `'Viridis'` | Colormap (`string`) |
| `opts.xmin` | `X:min()` | Clip minimum value (`number`) |
| `opts.xmax` | `X:max()` | Clip maximum value (`number`) |
| `opts.layoutopts` | — | Dict of additional layout options |

## vis.contour

This function draws a contour plot. It takes as input an `NxM` tensor `X`.

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.colormap` | `'Viridis'` | Colormap (`string`) |
| `opts.xmin` | `X:min()` | Clip minimum value (`number`) |
| `opts.xmax` | `X:max()` | Clip maximum value (`number`) |
| `opts.layoutopts` | — | Dict of additional layout options |

## vis.quiver

This function draws a quiver plot in which the direction and length of the arrows is determined by the `NxM` tensors `X` and `Y`. Two optional `NxM` tensors `gridX` and `gridY` can be provided that specify the offsets of the arrows.

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.normalize` | — | Length of longest arrows (`number`) |
| `opts.arrowheads` | `true` | Show arrow heads (`boolean`) |
| `opts.layoutopts` | — | Dict of additional layout options |

## vis.mesh

This function draws a mesh plot from a set of vertices defined in an `Nx2` or `Nx3` matrix `X`, and polygons defined in an optional `Mx2` or `Mx3` matrix `Y`.

**Supported opts:**

| Option | Description |
|--------|-------------|
| `opts.color` | Color (`string`) |
| `opts.opacity` | Opacity of polygons (`number` between 0 and 1) |
| `opts.layoutopts` | Dict of additional layout options |

## vis.dual_axis_lines

This function creates a line plot using Plotly with different Y-Axes.

- `X` = A numpy array of the range
- `Y1` = A numpy array of the same count as `X`
- `Y2` = A numpy array of the same count as `X`

<div style={{textAlign: 'center'}}>
  <img width="400" src="https://user-images.githubusercontent.com/19650074/198822367-666cc42e-4354-4a7a-8dd3-d8ff143f885d.gif" alt="Dual Axis Lines" />
</div>

**Supported opts:**

| Option | Description |
|--------|-------------|
| `opts.height` | Height of the plot |
| `opts.width` | Width of the plot |
| `opts.name_y1` | Axis name for Y1 plot |
| `opts.name_y2` | Axis name for Y2 plot |
| `opts.title` | Title of the plot |
| `opts.color_title_y1` | Color of the Y1 axis title |
| `opts.color_tick_y1` | Color of the Y1 axis ticks |
| `opts.color_title_y2` | Color of the Y2 axis title |
| `opts.color_tick_y2` | Color of the Y2 axis ticks |
| `opts.side` | Side for Y2 ticks: `'right'` or `'left'` |
| `opts.showlegend` | Display legends (`boolean`) |
| `opts.top` | Set the top margin |
| `opts.bottom` | Set the bottom margin |
| `opts.right` | Set the right margin |
| `opts.left` | Set the left margin |
