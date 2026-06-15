---
sidebar_position: 1
title: Installation
description: How to install Visdom
---

# Installation

Python and web clients come bundled with the Python server.

## Install from pip

```bash
pip install visdom
```

## Install from source

```bash
pip install git+https://github.com/fossasia/visdom
```

## Optional Dependencies

To save Plotly figures to image files from code (e.g. PNG/SVG) without using the browser download button, install `plotly` and `kaleido`:

```bash
pip install plotly kaleido
```

See [vis.plotlyplot](../api/basics.md#visplotlyplot) and [vis.save_plotly_figure](../api/basics.md#visplotlyplot) for details.
