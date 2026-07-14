---
sidebar_position: 4
title: Live Updates & Streaming
description: Stream data from training loops and update visualizations in real time
---

# Live Updates & Streaming

One of Visdom's core strengths is streaming live data from running experiments. You can append points to plots, replace data, or remove traces — all while your code continues to run.

## Appending data

Use `update='append'` to add new data points to an existing plot:

```python
import visdom
import numpy as np
import time

vis = visdom.Visdom()

# Create initial plot
win = vis.line(
    Y=[0.9], X=[1],
    opts=dict(title='Training Loss', xlabel='Epoch', ylabel='Loss'),
)

# Simulate training loop
for epoch in range(2, 100):
    loss = 0.9 * np.exp(-0.03 * epoch) + np.random.normal(0, 0.02)
    vis.line(Y=[loss], X=[epoch], win=win, update='append')
    time.sleep(0.05)
```

## Multiple live traces

Track multiple metrics in a single plot:

```python
win = vis.line(
    Y=np.column_stack([[0.9], [0.85]]),
    X=np.column_stack([[1], [1]]),
    opts=dict(title='Train vs Val Loss', legend=['Train', 'Val']),
)

for epoch in range(2, 100):
    train_loss = 0.9 * np.exp(-0.03 * epoch) + np.random.normal(0, 0.02)
    val_loss = 0.85 * np.exp(-0.025 * epoch) + np.random.normal(0, 0.03)

    vis.line(
        Y=np.column_stack([[train_loss], [val_loss]]),
        X=np.column_stack([[epoch], [epoch]]),
        win=win,
        update='append',
    )
```

## Named traces

When updating individual traces in a multi-trace plot, use `name` to target a specific one:

```python
win = vis.line(Y=[0], X=[0], name='accuracy',
               opts=dict(title='Metrics', showlegend=True))
vis.line(Y=[0], X=[0], win=win, name='f1_score', update='append')

for step in range(1, 200):
    vis.line(Y=[step * 0.005], X=[step], win=win, name='accuracy', update='append')
    vis.line(Y=[step * 0.004], X=[step], win=win, name='f1_score', update='append')
```

## Replacing data

Use `update='replace'` to completely replace the data in a window:

```python
# Histogram that updates each epoch
for epoch in range(50):
    weights = np.random.randn(1000) * (1.0 / (epoch + 1))
    vis.histogram(X=weights, win='weights',
                  opts=dict(title=f'Weight Distribution (Epoch {epoch})', numbins=50))
```

## Removing traces

Remove a specific trace by name:

```python
vis.line(Y=[0], X=[0], win=win, name='old_trace', update='remove')
```

## Updating heatmaps

Heatmaps support row and column appending:

```python
import numpy as np

# Create initial heatmap
data = np.random.rand(5, 5)
vis.heatmap(X=data, win='hm', opts=dict(title='Growing Heatmap'))

# Append a new row
vis.heatmap(X=np.random.rand(1, 5), win='hm', update='appendRow')

# Append a new column
vis.heatmap(X=np.random.rand(6, 1), win='hm', update='appendColumn')
```

## Auto-creating windows

If you use `update='append'` with a `win` that doesn't exist yet, Visdom will create it automatically:

```python
# No need to create the window first
vis.line(Y=[loss], X=[1], win='auto_plot',
         opts=dict(title='Auto-created'), update='append')
```

## Checking if a window exists

Before updating, you can check whether a window already exists:

```python
if vis.win_exists('my_plot'):
    vis.line(Y=[val], X=[step], win='my_plot', update='append')
else:
    vis.line(Y=[val], X=[step], win='my_plot',
             opts=dict(title='My Plot', xlabel='Step'))
```

## Logging for replay

Record all operations to a file so you can replay them later:

```python
# Record everything
vis = visdom.Visdom(log_to_filename='experiment_log.json')

# ... run your experiment ...

# Later, replay on a new server
vis2 = visdom.Visdom(server='http://new-server')
vis2.replay_log('experiment_log.json')
```

## Offline mode

Run without a server — all calls are saved to a log file:

```python
vis = visdom.Visdom(offline=True, log_to_filename='offline_log.json')

vis.line(Y=[1, 2, 3], X=[1, 2, 3], opts=dict(title='Offline Plot'))

# Later, replay to a running server
vis_online = visdom.Visdom()
vis_online.replay_log('offline_log.json')
```
