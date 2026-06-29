---
sidebar_position: 3
title: Callbacks
description: Register event handlers on Visdom windows
---

# Callbacks

The Python Visdom implementation supports callbacks on a window. The demo shows an example of this in the form of an editable text pad. The functionality of these callbacks allows the Visdom object to receive and react to events that happen in the frontend.

## Registering Event Handlers

You can subscribe a window to events by adding a function to the event handlers dict for the window id you want to subscribe by calling:

```python
viz.register_event_handler(handler, win_id, env=None)
```

Specifying the environment name prevents event handlers from firing across different environments with the same window id. Multiple handlers can be registered to the same window. You can remove event handlers from a window using:

```python
viz.clear_event_handlers(win_id, env=None)
```

## Event Data

When an event occurs to that window, your callbacks will be called on a dict containing:

- `event_type`: one of the below event types
- `pane_data`: all of the stored contents for that window including layout and content
- `eid`: the current environment id
- `target`: the window id the event is called on

## Supported Events

### 1. Close
Triggers when a window is closed. Returns a dict with only the standard fields listed above.

### 2. KeyPress
Triggers when a key is pressed. Contains additional parameters:
- `key` — A string representation of the key pressed (applying state modifiers such as SHIFT)
- `key_code` — The javascript event keycode for the pressed key (no modifiers)

### 3. PropertyUpdate
Triggers when a property is updated in Property pane:
- `propertyId` — Position in properties list
- `value` — New property value

### 4. Click
Triggers when Image pane is clicked on:
- `image_coord` — dictionary with the fields `x` and `y` for the click coordinates in the coordinate frame of the possibly zoomed/panned image (*not* the enclosing pane)
