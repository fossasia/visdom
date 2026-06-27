---
sidebar_position: 2
title: Basics
description: Basic visualization functions — image, text, audio, video, SVG, and more
---

# Basics

![Visdom Dashboard](https://user-images.githubusercontent.com/19650074/198747904-7a8a580f-851a-45fb-8f45-94e54a910ee2.png)

## vis.image

```python
vis.image(img, win=None, env=None, opts=None)
```

This function draws an `img`. It takes as input an `CxHxW` tensor `img` that contains the image. Most Python image libraries (e.g. OpenCV, PIL, matplotlib) return images in `HxWxC` format. Passing images in that format will raise errors or lead to incorrect rendering.

```python
import numpy as np

# Random RGB image (CxHxW format)
vis.image(np.random.rand(3, 256, 256), opts=dict(title='Random'))

# Convert HxWxC -> CxHxW before passing to vis.image
img = img.transpose(2, 0, 1)   # NumPy
img = img.permute(2, 0, 1)     # PyTorch
```

**Supported opts:**

| Option | Description |
|--------|-------------|
| `opts.jpgquality` | JPG quality (`number` 0-100). If defined image will be saved as JPG to reduce file size. If not defined image will be saved as PNG. |
| `opts.caption` | Caption for the image |
| `opts.store_history` | Keep all images stored to the same window and attach a slider to the bottom that will let you select the image to view. You must always provide this opt when sending new images to an image with history. |

:::note
You can use alt on an image pane to view the x/y coordinates of the cursor. You can also ctrl-scroll to zoom, alt scroll to pan vertically, and alt-shift scroll to pan horizontally. Double click inside the pane to restore the image to default.
:::

## vis.images

```python
vis.images(tensor, nrow=8, padding=2, win=None, env=None, opts=None)
```

This function draws a list of `images`. It takes an input `B x C x H x W` tensor or a `list of images` all of the same size. It makes a grid of images of size (B / nrow, nrow).

```python
# Display a grid of 16 random images
vis.images(np.random.rand(16, 3, 64, 64), nrow=4, opts=dict(title='Image Grid'))
```

**Supported arguments and opts:**

| Option | Description |
|--------|-------------|
| `nrow` | Number of images in a row |
| `padding` | Padding around the image, equal padding around all 4 sides |
| `opts.jpgquality` | JPG quality (`number` 0-100) |
| `opts.caption` | Caption for the image |

## vis.text

```python
vis.text(text, win=None, env=None, opts=None, append=False)
```

This function prints text in a box. You can use this to embed arbitrary HTML. It takes as input a `text` string. No specific `opts` are currently supported.

```python
vis.text('Hello, world!')
vis.text('<h1>HTML works too</h1><p>With <b>formatting</b></p>')

# Append text to an existing window
vis.text('First line', win='log')
vis.text('<br>Second line', win='log', append=True)
```

## vis.properties

```python
vis.properties(data, win=None, env=None, opts=None)
```

This function shows editable properties in a pane. Properties are expected to be a List of Dicts:

```python
properties = [
    {'type': 'text', 'name': 'Text input', 'value': 'initial'},
    {'type': 'number', 'name': 'Number input', 'value': '12'},
    {'type': 'button', 'name': 'Button', 'value': 'Start'},
    {'type': 'checkbox', 'name': 'Checkbox', 'value': True},
    {'type': 'select', 'name': 'Select', 'value': 1, 'values': ['Red', 'Green', 'Blue']},
]

vis.properties(properties)
```

**Supported types:**
- **text**: string
- **number**: decimal number
- **button**: button labeled with "value"
- **checkbox**: boolean value rendered as a checkbox
- **select**: multiple values select box
  - `value`: id of selected value (zero based)
  - `values`: list of possible values

Callbacks are called on property value update:
- `event_type`: `"PropertyUpdate"`
- `propertyId`: position in the `properties` list
- `value`: new value

## vis.audio

```python
vis.audio(tensor=None, audiofile=None, win=None, env=None, opts=None)
```

This function plays audio. It takes as input the filename of the audio file or an `N` tensor containing the waveform (use an `Nx2` matrix for stereo audio).

```python
# From a file
vis.audio(audiofile='sound.wav')

# From a tensor (mono, 1 second at 44100 Hz)
import numpy as np
t = np.linspace(0, 1, 44100)
waveform = np.sin(2 * np.pi * 440 * t)  # 440 Hz sine wave
vis.audio(waveform, opts=dict(sample_frequency=44100))
```

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.sample_frequency` | `44100` | Sample frequency (`integer` > 0) |

:::note
Visdom uses scipy to convert tensor inputs to wave files. Some versions of Chrome are known not to play these wave files (Firefox and Safari work fine).
:::

## vis.video

```python
vis.video(tensor=None, dim="LxHxWxC", videofile=None, win=None, env=None, opts=None)
```

This function plays a video. It takes as input the filename of the video `videofile` or a `LxHxWxC`-sized `tensor` containing all the frames of the video as input.

```python
# From a file
vis.video(videofile='clip.mp4')

# From a tensor (10 frames, 64x64, RGB)
import numpy as np
frames = np.random.randint(0, 255, (10, 64, 64, 3), dtype=np.uint8)
vis.video(tensor=frames)
```

**Supported opts:**

| Option | Default | Description |
|--------|---------|-------------|
| `opts.fps` | `25` | FPS for the video (`integer` > 0) |

:::note
Using `tensor` input requires that ffmpeg is installed and working. Your ability to play video may depend on the browser you use: your browser has to support the Theano codec in an OGG container (Chrome supports this).
:::

## vis.svg

```python
vis.svg(svgstr=None, svgfile=None, win=None, env=None, opts=None)
```

This function draws an SVG object. It takes as input a SVG string `svgstr` or the name of an SVG file `svgfile`. No specific `opts` are supported.

```python
# From a string
vis.svg(svgstr='<svg><circle cx="50" cy="50" r="40" fill="blue"/></svg>')

# From a file
vis.svg(svgfile='diagram.svg')
```

## vis.matplot

```python
vis.matplot(plot, opts=None, env=None, win=None)
```

This function draws a Matplotlib `plot`. The function supports one plot-specific option: `resizable`.

```python
import matplotlib.pyplot as plt

plt.plot([1, 2, 3], [4, 5, 6])
plt.title('Matplotlib in Visdom')
vis.matplot(plt)
```

:::note
When set to `True` the plot is resized with the pane. You need `beautifulsoup4` and `lxml` packages installed to use this option.
:::

:::note
`matplot` is not rendered using the same backend as plotly plots, and is somewhat less efficient. Using too many matplot windows may degrade visdom performance.
:::

## vis.plotlyplot

```python
vis.plotlyplot(figure, win=None, env=None, save_path=None, save_kwargs=None)
```

This function draws a Plotly `Figure` object. It does not explicitly take options as it assumes you have already explicitly configured the figure's `layout`.

:::note
You must have the `plotly` Python package installed to use this function. It can typically be installed by running `pip install plotly`.
:::

**Saving plots as images from code (without using the browser download button):** Pass `save_path` to save the figure to a file when plotting, e.g. `vis.plotlyplot(fig, save_path="plot.png")`. You can also save a figure without displaying it using `vis.save_plotly_figure(fig, "plot.png")`. Both require the optional `kaleido` package: `pip install kaleido`.

```python
import plotly.graph_objects as go
from visdom import Visdom

viz = Visdom()
fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[4, 5, 6], mode="lines+markers"))

viz.plotlyplot(fig, save_path="my_plot.png")
viz.save_plotly_figure(fig, "my_plot.png")
```

## vis.embeddings

```python
vis.embeddings(features, labels, data_getter=None, data_type=None, win=None, env=None, opts=None)
```

This function visualizes a collection of features using the [Barnes-Hut t-SNE algorithm](https://github.com/lvdmaaten/bhtsne).

**Arguments:**

| Argument | Description |
|----------|-------------|
| `features` | A list of tensors |
| `labels` | A list of corresponding labels for the tensors |
| `data_getter` | (optional) A function that takes an index into the features array and returns a summary representation of the tensor. If set, `data_type` must also be set. |
| `data_type` | (optional) Currently the only acceptable value is `"html"` |

We currently assume that there are no more than 10 unique labels, in the future we hope to provide a colormap in opts for other cases.

From the UI you can also draw a lasso around a subset of features. This will rerun the t-SNE visualization on the selected subset.

## vis.save

```python
vis.save(envs)
```

This function saves the `envs` that are alive on the visdom server. It takes input a list of env ids to be saved.

```python
# Save specific environments
vis.save(['main', 'experiment_1'])
```
