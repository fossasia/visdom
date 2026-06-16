---
sidebar_position: 6
title: Network Graph
description: Draw network graphs with nodes and edges
---

# Network Graph

```python
vis.graph(edges, edgeLabels=None, nodeLabels=None, opts=dict(), env=None, win=None)
```

This function draws a graph, in which the nodes and edges are taken from a 2-D matrix of size `[N, 2]` where each row contains a source and destination node value. The numeric value used to define nodes should be strictly between `0` and `n-1`, where `n` is the number of nodes.

## Example

```python
import numpy as np

# Define edges: 4 nodes (0-3), 4 edges
edges = np.array([
    [0, 1],
    [1, 2],
    [2, 3],
    [3, 0],
])

vis.graph(
    edges,
    nodeLabels=['Start', 'Process', 'Review', 'End'],
    edgeLabels=['begin', 'develop', 'check', 'loop'],
    opts=dict(
        title='Workflow Graph',
        directed=True,
        showEdgeLabels=True,
        width=600,
        height=600,
    ),
)
```

## Arguments

| Argument | Description |
|----------|-------------|
| `edges` | 2D array of shape `[N, 2]` defining source-destination node pairs |
| `edgeLabels` | List of custom edge labels. If not provided each edge gets a label "source-destination" (e.g. "1-2"). Size should equal the number of edges. |
| `nodeLabels` | List of custom node labels. If not provided each node gets a label same as its numeric value. Size should equal the number of nodes. |

## Supported Options

| Option | Default | Description |
|--------|---------|-------------|
| `opts.height` | `500` | Height of the plot |
| `opts.width` | `500` | Width of the plot |
| `opts.directed` | `false` | Whether the plot should have directed arrows |
| `opts.showVertexLabels` | `true` | Whether to show vertex labels |
| `opts.showEdgeLabels` | `false` | Whether to show edge labels |
| `opts.scheme` | `"same"` | Whether all nodes should have `"same"` color or `"different"` |
