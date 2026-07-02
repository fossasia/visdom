---
sidebar_position: 8
title: PyTorch & NumPy Integration
description: Using Visdom with PyTorch tensors and NumPy arrays for experiment tracking
---

# PyTorch & NumPy Integration

Visdom works natively with both PyTorch tensors and NumPy arrays. This makes it easy to visualize data directly from your training pipelines.

## PyTorch tensors

All Visdom functions accept PyTorch tensors. They are automatically converted:

```python
import torch
import visdom

vis = visdom.Visdom()

# Line plot from PyTorch tensors
x = torch.linspace(0, 10, 100)
y = torch.sin(x)
vis.line(Y=y, X=x, opts=dict(title='Sine (PyTorch)'))

# Image from PyTorch tensor (CxHxW)
img = torch.rand(3, 224, 224)
vis.image(img, opts=dict(title='Random Image'))

# Scatter from PyTorch tensor
points = torch.randn(200, 2)
vis.scatter(X=points, opts=dict(title='Point Cloud'))
```

## Training loop visualization

A typical training loop with Visdom logging:

```python
import torch
import torch.nn as nn
import torch.optim as optim
import visdom
import numpy as np

vis = visdom.Visdom(env='cifar10_training')

model = MyModel()
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)

# Create initial plots
loss_win = vis.line(Y=[0], X=[0], opts=dict(
    title='Training Loss',
    xlabel='Iteration',
    ylabel='Loss',
))

acc_win = vis.line(
    Y=np.column_stack([[0], [0]]),
    X=np.column_stack([[0], [0]]),
    opts=dict(
        title='Accuracy',
        xlabel='Epoch',
        ylabel='%',
        legend=['Train', 'Val'],
    ),
)

step = 0
for epoch in range(num_epochs):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        optimizer.zero_grad()
        output = model(data)
        loss = criterion(output, target)
        loss.backward()
        optimizer.step()

        # Log loss every 10 steps
        step += 1
        if step % 10 == 0:
            vis.line(Y=[loss.item()], X=[step],
                     win=loss_win, update='append')

    # Log epoch-level accuracy
    train_acc = evaluate(model, train_loader)
    val_acc = evaluate(model, val_loader)
    vis.line(
        Y=np.column_stack([[train_acc], [val_acc]]),
        X=np.column_stack([[epoch], [epoch]]),
        win=acc_win,
        update='append',
    )

    # Visualize a batch of predictions
    images, labels = next(iter(val_loader))
    vis.images(images[:16], nrow=4, win='predictions',
               opts=dict(title=f'Predictions (Epoch {epoch})'))

vis.save([vis.env])
```

## Visualizing model weights

```python
# Weight distribution
for name, param in model.named_parameters():
    if 'weight' in name:
        vis.histogram(
            X=param.data.cpu().numpy().flatten(),
            win=f'weight_{name}',
            opts=dict(title=f'Weights: {name}', numbins=50),
        )
```

## Visualizing feature maps

```python
# Hook to capture feature maps
activation = {}

def get_activation(name):
    def hook(model, input, output):
        activation[name] = output.detach()
    return hook

model.conv1.register_forward_hook(get_activation('conv1'))

# Run a forward pass
output = model(sample_image.unsqueeze(0))

# Display feature maps as an image grid
features = activation['conv1'].squeeze(0)  # CxHxW
# Show first 16 channels
vis.images(
    features[:16].unsqueeze(1),  # add channel dim for grayscale
    nrow=4,
    opts=dict(title='Conv1 Feature Maps'),
)
```

## Confusion matrix

```python
from sklearn.metrics import confusion_matrix
import numpy as np

y_true = [...]
y_pred = [...]
classes = ['cat', 'dog', 'bird', 'fish']

cm = confusion_matrix(y_true, y_pred)
vis.heatmap(
    X=cm,
    opts=dict(
        title='Confusion Matrix',
        columnnames=classes,
        rownames=classes,
        colormap='Blues',
    ),
)
```

## NumPy arrays

All the above examples work identically with NumPy arrays:

```python
import numpy as np

vis.line(Y=np.sin(np.linspace(0, 10, 100)),
         X=np.linspace(0, 10, 100))

vis.image(np.random.rand(3, 128, 128))

vis.scatter(X=np.random.randn(100, 2))
```

## Tips

- **Detach tensors**: Always call `.detach()` before passing gradients-enabled tensors to avoid memory leaks.
- **Move to CPU**: Visdom runs on the CPU. If your tensors are on GPU, use `.cpu()` first.
- **Image format**: Remember to use `CxHxW` format (channels first), not `HxWxC`.
- **Save environments**: Call `vis.save([env])` periodically to persist your dashboards.
