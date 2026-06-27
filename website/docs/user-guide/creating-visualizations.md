---
sidebar_position: 2
title: Creating Visualizations
description: All the plot types and media you can display in Visdom
---

# Creating Visualizations

Visdom supports a wide range of visualization types — from simple text and images to interactive Plotly charts, matplotlib figures, and more. Every visualization lives in a **window** that you can drag, resize, and organize.

## Text & HTML

Use `vis.text()` to display text, logs, or arbitrary HTML:

```python
vis.text('Hello, Visdom!')

# Rich HTML content
vis.text('''
<h3>Experiment Summary</h3>
<ul>
  <li><b>Model:</b> ResNet-50</li>
  <li><b>Dataset:</b> CIFAR-10</li>
  <li><b>Accuracy:</b> 93.2%</li>
</ul>
''', win='summary')

# Append text to an existing window (useful for logging)
vis.text('Epoch 1: loss=0.45', win='log')
vis.text('<br>Epoch 2: loss=0.32', win='log', append=True)
vis.text('<br>Epoch 3: loss=0.28', win='log', append=True)
```

## Images

### Single image

Display a single image with `vis.image()`. The input must be a `CxHxW` tensor (channels first):

```python
import numpy as np

# Random RGB image
vis.image(np.random.rand(3, 256, 256), opts=dict(title='Random'))

# From a file using PIL
from PIL import Image
img = np.array(Image.open('photo.jpg'))  # HxWxC
img = img.transpose(2, 0, 1)            # Convert to CxHxW
vis.image(img, opts=dict(title='Photo'))
```

:::tip Image format
Most libraries (OpenCV, PIL, matplotlib) return images in `HxWxC` format. Always transpose to `CxHxW` before passing to `vis.image()`:
```python
img = img.transpose(2, 0, 1)   # NumPy
img = img.permute(2, 0, 1)     # PyTorch
```
:::

### Image grid

Display multiple images in a grid with `vis.images()`:

```python
# 16 random images in a 4-column grid
vis.images(np.random.rand(16, 3, 64, 64), nrow=4, opts=dict(title='Image Grid'))
```

### Image history

Track how an image changes over time (e.g., generated images during GAN training):

```python
for epoch in range(100):
    generated = generate_image(epoch)  # CxHxW
    vis.image(generated, win='gen',
              opts=dict(title='Generated', store_history=True))
```

A slider appears at the bottom of the window to browse through all stored images.

## Line Plots

Line plots are the most common visualization for tracking training metrics:

```python
import numpy as np

# Single line
x = np.linspace(0, 10, 200)
vis.line(Y=np.sin(x), X=x, opts=dict(title='Sine Wave'))

# Multiple lines
vis.line(
    Y=np.column_stack([np.sin(x), np.cos(x), np.sin(2 * x)]),
    X=x,
    opts=dict(
        title='Multiple Lines',
        legend=['sin(x)', 'cos(x)', 'sin(2x)'],
        xlabel='x',
        ylabel='y',
    ),
)
```

![Interactive Smoothing](https://user-images.githubusercontent.com/19650074/159366736-1f5d8099-0ea5-4a3b-af17-49d3e24cb32c.gif)

:::tip Smoothing
Click the **~** icon in the top-right corner of any line plot to enable Savitzky-Golay smoothing. Useful for noisy training curves.
:::

## Scatter Plots

2D and 3D scatter plots with optional class labels:

```python
# 2D scatter with two classes
X = np.random.randn(200, 2)
Y = (X[:, 0] > 0).astype(int) + 1  # labels 1 or 2
vis.scatter(X, Y, opts=dict(
    title='2D Scatter',
    legend=['Negative', 'Positive'],
    markersize=6,
    xlabel='Feature 1',
    ylabel='Feature 2',
))

# 3D scatter
vis.scatter(
    X=np.random.randn(200, 3),
    opts=dict(title='3D Scatter', markersize=4),
)
```

## Bar Charts

```python
# Simple bar chart
vis.bar(
    X=np.array([28, 55, 43, 91, 67]),
    opts=dict(
        title='Weekly Sales',
        rownames=['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
        ylabel='Units',
    ),
)

# Stacked bar chart
vis.bar(
    X=np.random.rand(5, 3) * 100,
    opts=dict(
        title='Sales by Category',
        stacked=True,
        legend=['Electronics', 'Clothing', 'Food'],
        rownames=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'],
    ),
)
```

## Heatmaps

```python
# Confusion matrix as heatmap
confusion = np.array([
    [50, 2, 1],
    [3, 45, 5],
    [0, 4, 48],
])
vis.heatmap(
    X=confusion,
    opts=dict(
        title='Confusion Matrix',
        columnnames=['Cat', 'Dog', 'Bird'],
        rownames=['Cat', 'Dog', 'Bird'],
        colormap='Viridis',
    ),
)
```

## Histograms

```python
# Distribution of model weights
vis.histogram(
    X=np.random.randn(10000),
    opts=dict(title='Weight Distribution', numbins=50),
)
```

## Box Plots

```python
# Compare distributions across experiments
vis.boxplot(
    X=np.random.randn(100, 4),
    opts=dict(
        title='Experiment Comparison',
        legend=['Baseline', 'Model A', 'Model B', 'Model C'],
    ),
)
```

## Surface & Contour Plots

```python
# 3D surface
x = np.linspace(-3, 3, 50)
y = np.linspace(-3, 3, 50)
X, Y = np.meshgrid(x, y)
Z = np.sin(np.sqrt(X**2 + Y**2))

vis.surf(X=Z, opts=dict(title='Surface Plot', colormap='Viridis'))
vis.contour(X=Z, opts=dict(title='Contour Plot', colormap='Viridis'))
```

## Matplotlib Figures

Render any matplotlib figure directly in Visdom:

```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(10, 4))
axes[0].plot([1, 2, 3], [1, 4, 9])
axes[0].set_title('Quadratic')
axes[1].bar(['A', 'B', 'C'], [3, 7, 5])
axes[1].set_title('Categories')
plt.tight_layout()

vis.matplot(fig)
plt.close(fig)
```

:::note Performance
`vis.matplot()` renders as an image, not as an interactive Plotly chart. For interactive plots, use the native Visdom plotting functions or `vis.plotlyplot()`.
:::

## Plotly Figures

For full Plotly interactivity, use `vis.plotlyplot()`:

```python
import plotly.graph_objects as go

fig = go.Figure()
fig.add_trace(go.Scatter(x=[1, 2, 3, 4], y=[10, 11, 12, 13], mode='lines+markers', name='Series A'))
fig.add_trace(go.Bar(x=[1, 2, 3, 4], y=[5, 4, 6, 7], name='Series B'))
fig.update_layout(title='Mixed Plotly Chart')

vis.plotlyplot(fig)
```

You can also save the figure to disk:

```python
vis.plotlyplot(fig, save_path='chart.png')
# or without displaying:
vis.save_plotly_figure(fig, 'chart.png')
```

:::note
Requires `pip install plotly`. Saving to file also requires `pip install kaleido`.
:::

## Audio & Video

```python
# Audio from file
vis.audio(audiofile='sample.wav')

# Audio from tensor (440 Hz sine wave, 1 second)
import numpy as np
t = np.linspace(0, 1, 44100)
wave = np.sin(2 * np.pi * 440 * t)
vis.audio(wave, opts=dict(sample_frequency=44100, title='440 Hz Tone'))

# Video from file
vis.video(videofile='clip.mp4')
```

## SVG

```python
vis.svg(svgstr='''
<svg width="200" height="200">
  <circle cx="100" cy="100" r="80" fill="#2980b9" opacity="0.7"/>
  <text x="100" y="110" text-anchor="middle" fill="white" font-size="20">Visdom</text>
</svg>
''')
```

## Network Graphs

```python
import numpy as np

edges = np.array([[0, 1], [1, 2], [2, 3], [3, 0], [1, 3]])
vis.graph(
    edges,
    nodeLabels=['Input', 'Conv1', 'Conv2', 'Output'],
    opts=dict(title='Network Architecture', directed=True, width=500, height=500),
)
```

## Dual-Axis Line Plots

Plot two series with different scales on the same chart:

```python
import numpy as np

epochs = np.arange(1, 51)
loss = 2.0 * np.exp(-0.05 * epochs) + np.random.normal(0, 0.05, 50)
lr = 0.01 * (0.95 ** epochs)

vis.dual_axis_lines(
    X=epochs, Y1=loss, Y2=lr,
    opts=dict(title='Loss & LR', name_y1='Loss', name_y2='Learning Rate'),
)
```

<div style={{textAlign: 'center'}}>
  <img width="450" src="https://user-images.githubusercontent.com/19650074/198822367-666cc42e-4354-4a7a-8dd3-d8ff143f885d.gif" alt="Dual Axis Lines" />
</div>

## Sunburst Charts

```python
vis.sunburst(
    labels=['Model', 'Encoder', 'Decoder', 'Attention', 'FFN', 'Cross-Attn', 'Self-Attn'],
    parents=['', 'Model', 'Model', 'Encoder', 'Encoder', 'Decoder', 'Decoder'],
    values=[100, 60, 40, 30, 30, 20, 20],
    opts=dict(title='Model Architecture'),
)
```

## t-SNE Embeddings

Visualize high-dimensional features with interactive t-SNE:

```python
features = [np.random.randn(128) for _ in range(500)]
labels = [i % 5 for i in range(500)]  # 5 classes

vis.embeddings(features, labels)
```

You can draw a lasso around a cluster in the UI to re-run t-SNE on just that subset.
