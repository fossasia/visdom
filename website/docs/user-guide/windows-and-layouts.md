---
sidebar_position: 5
title: Windows & Layouts
description: Arrange, resize, save, and restore your visualization layouts
---

# Windows & Layouts

Every visualization in Visdom lives in a **window**. Windows can be moved, resized, closed, and organized into saved layouts.

<div style={{textAlign: 'center'}}>
  <img width="500" src="https://user-images.githubusercontent.com/19650074/198821065-6666cb22-d34a-4839-ae19-f6f6a4a1bae4.png" alt="Visdom Windows" />
</div>

## Window basics

- **Drag** the title bar to move a window
- **Drag** the edges to resize
- **Click X** to close
- **Click the download icon** to save contents (plots as SVG, images as PNG)

:::tip
Use your browser's zoom (Ctrl+/Ctrl-) to adjust the overall scale of the dashboard.
:::

## Window IDs

Every window has an ID. You can either let Visdom auto-generate one or specify it yourself:

```python
# Auto-generated ID (returned by the function)
win_id = vis.line(Y=[1, 2, 3], X=[1, 2, 3])
print(win_id)  # e.g. "window_38fa9db440d6a4"

# Explicit ID (easier to reference later)
vis.line(Y=[1, 2, 3], X=[1, 2, 3], win='loss_plot')
vis.line(Y=[4, 5, 6], X=[4, 5, 6], win='loss_plot', update='append')
```

## Closing windows

```python
# Close a specific window
vis.close(win='loss_plot')

# Close all windows in the current environment
vis.close()

# Close all windows in a specific environment
vis.close(env='experiment_1')
```

## Getting window data

Retrieve the data stored in a window:

```python
# Single window
data = vis.get_window_data(win='loss_plot', env='main')

# All windows in an environment
all_data = vis.get_window_data(env='main')
```

## Editing plot parameters

Click the **edit** button (pencil icon) in the top-right corner of any plot window to inspect and modify parameters on the fly:

<div style={{textAlign: 'center'}}>
  <img width="400" src="https://user-images.githubusercontent.com/19650074/156751970-0915757d-8bf0-4a6d-a510-1d34a918e47a.gif" alt="Editable Plot Parameters" />
</div>

Change a parameter value and the plot updates instantly — no code changes needed.

## State & persistence

Visdom automatically caches your visualization state. If you reload the browser, all windows reappear in the same position.

<div style={{textAlign: 'center'}}>
  <img width="400" src="https://user-images.githubusercontent.com/19650074/198821344-cb8c424e-455c-4249-b3b4-5554309a5ec7.gif" alt="State Persistence" />
</div>

- **Auto-save**: Windows are cached automatically
- **Manual save**: Click the save button or call `vis.save(['main'])`
- **Fork**: Enter a new name when saving to create a copy of the environment

## Views

Views let you save and switch between different window arrangements within the same environment.

<div style={{textAlign: 'center'}}>
  <img width="300" src="https://user-images.githubusercontent.com/19650074/198821420-458c863b-c304-4d10-8906-0cc2f0c20241.png" alt="Views" />
</div>

### Saving a view

1. Arrange your windows the way you want
2. Click the **folder** icon
3. Enter a view name and save

Views store window positions and sizes in `$HOME/.visdom/view/layouts.json`.

### Switching views

Use the view dropdown to switch between saved layouts:

<div style={{textAlign: 'center'}}>
  <img width="600" src="https://user-images.githubusercontent.com/19650074/198821436-6c7957b5-dd67-4afc-9fc3-4bf074137022.gif" alt="Switching Views" />
</div>

### Re-packing

Click the **repack** icon (grid icon) to automatically arrange windows into an optimal grid layout.

## Filtering windows

Use the **filter** box to search windows by title using a regular expression:

<div style={{textAlign: 'center'}}>
  <img width="300" src="https://user-images.githubusercontent.com/19650074/198821379-eeebd8a2-bcab-407a-b47f-9b2d0290c23e.png" alt="Filter" />
</div>

This is useful when you have many windows — type a regex pattern and only matching windows will be shown. Clear the filter to restore the full view.

<div style={{textAlign: 'center'}}>
  <img width="500" src="https://user-images.githubusercontent.com/19650074/198821402-4702611e-1038-4093-8cd5-9c8120444211.gif" alt="Filter Restore" />
</div>
