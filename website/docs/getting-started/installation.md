---
sidebar_position: 1
title: Installation
description: How to install Visdom
---

# Installation

Python and web clients come bundled with the Python server.

## Requirements

- **Python** 3.6 or later
- **pip** (comes with Python)
- A modern web browser (Chrome, Firefox, Safari, Edge)

## Install from pip

```bash
pip install visdom
```

## Install from source

```bash
pip install git+https://github.com/fossasia/visdom
```

For development, clone and install in editable mode:

```bash
git clone https://github.com/fossasia/visdom.git
cd visdom
pip install -e .
```

## Using a Virtual Environment

It is recommended to install Visdom inside a virtual environment to avoid dependency conflicts:

```bash
python -m venv visdom-env
source visdom-env/bin/activate   # Linux/macOS
# visdom-env\Scripts\activate    # Windows

pip install visdom
```

## Optional Dependencies

To save Plotly figures to image files from code (e.g. PNG/SVG) without using the browser download button, install `plotly` and `kaleido`:

```bash
pip install plotly kaleido
```

See [vis.plotlyplot](../api/basics.md#visplotlyplot) and [vis.save_plotly_figure](../api/basics.md#visplotlyplot) for details.

## Verifying the Installation

After installing, verify everything works:

```bash
# Check the installed version
python -c "import visdom; print(visdom.__version__)"

# Start the server
visdom
```

Then open `http://localhost:8097` in your browser. You should see the Visdom dashboard.

## Troubleshooting

### Port already in use

If port 8097 is occupied, start Visdom on a different port:

```bash
visdom -port 8098
```

### Permission errors

If you encounter permission errors during installation, use `--user`:

```bash
pip install --user visdom
```

### Module not found

If `visdom` command is not found after installation, ensure your Python scripts directory is on your `PATH`, or run directly:

```bash
python -m visdom.server
```
