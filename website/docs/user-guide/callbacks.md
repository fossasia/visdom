---
sidebar_position: 6
title: Callbacks & Interactivity
description: Register event handlers to react to user interactions in the browser
---

# Callbacks & Interactivity

Visdom supports **callbacks** — Python functions that are triggered when a user interacts with a visualization in the browser. This enables building interactive dashboards where UI actions drive server-side logic.

## Registering event handlers

Subscribe to events on a specific window:

```python
def my_handler(event):
    print(f"Event: {event['event_type']}")
    print(f"Window: {event['target']}")

vis.register_event_handler(my_handler, 'my_window')
```

You can register multiple handlers on the same window. Specify `env` to prevent cross-environment firing:

```python
vis.register_event_handler(my_handler, 'my_window', env='main')
```

## Removing event handlers

```python
vis.clear_event_handlers('my_window')
vis.clear_event_handlers('my_window', env='main')  # env-specific
```

## Event data

Every callback receives a dictionary with:

| Field | Description |
|-------|-------------|
| `event_type` | The type of event (see below) |
| `pane_data` | All stored contents for that window (layout + content) |
| `eid` | The current environment ID |
| `target` | The window ID the event fired on |

## Event types

### Close

Fired when a window is closed by the user.

```python
def on_close(event):
    print(f"Window {event['target']} was closed")

vis.register_event_handler(on_close, 'my_window')
```

### KeyPress

Fired when a key is pressed while a window is focused.

| Extra field | Description |
|-------------|-------------|
| `key` | String of the key pressed (with modifiers like SHIFT) |
| `key_code` | JavaScript keyCode (no modifiers) |

```python
def on_key(event):
    print(f"Key pressed: {event['key']} (code: {event['key_code']})")

vis.register_event_handler(on_key, 'my_window')
```

### PropertyUpdate

Fired when a property value changes in a `vis.properties()` pane.

| Extra field | Description |
|-------------|-------------|
| `propertyId` | Index in the properties list |
| `value` | New value |

```python
properties = [
    {'type': 'text', 'name': 'Learning Rate', 'value': '0.001'},
    {'type': 'checkbox', 'name': 'Use Augmentation', 'value': True},
    {'type': 'button', 'name': 'Retrain', 'value': 'Start'},
]

win = vis.properties(properties)

def on_property(event):
    prop_id = event['propertyId']
    value = event['value']
    name = properties[prop_id]['name']
    print(f"{name} changed to {value}")

    if name == 'Retrain':
        print("Retraining triggered!")

vis.register_event_handler(on_property, win)
```

### Click

Fired when the user clicks on an image pane.

| Extra field | Description |
|-------------|-------------|
| `image_coord` | Dict with `x` and `y` in the image's coordinate frame (accounts for zoom/pan) |

```python
def on_click(event):
    coord = event['image_coord']
    print(f"Clicked at ({coord['x']}, {coord['y']})")

vis.register_event_handler(on_click, 'my_image')
```

## Interactive dashboard example

Combine properties with callbacks to build a simple control panel:

```python
import visdom
import numpy as np

vis = visdom.Visdom()

# Control panel
controls = [
    {'type': 'select', 'name': 'Function', 'value': 0, 'values': ['sin', 'cos', 'tan']},
    {'type': 'number', 'name': 'Frequency', 'value': '1'},
    {'type': 'button', 'name': 'Plot', 'value': 'Generate'},
]
ctrl_win = vis.properties(controls)

def on_update(event):
    if event['event_type'] != 'PropertyUpdate':
        return

    # Read current values
    func_name = controls[0]['values'][int(controls[0]['value'])]
    freq = float(controls[1]['value'])

    # Update stored values
    if event['propertyId'] == 0:
        controls[0]['value'] = event['value']
        func_name = controls[0]['values'][int(event['value'])]
    elif event['propertyId'] == 1:
        controls[1]['value'] = event['value']
        freq = float(event['value'])

    # Re-plot when button is clicked
    if event['propertyId'] == 2:
        x = np.linspace(0, 4 * np.pi, 300)
        func = getattr(np, func_name)
        vis.line(Y=func(freq * x), X=x, win='output',
                 opts=dict(title=f'{func_name}({freq}x)'))

vis.register_event_handler(on_update, ctrl_win)
```

:::note
Callbacks require `use_incoming_socket=True` (the default). If you disabled it, re-enable it to use callbacks.
:::
