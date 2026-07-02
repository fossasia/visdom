---
sidebar_position: 4
title: Views & Filters
description: Organize and filter your visualization windows
---

# Views & Filters

## State

Once you've created a few visualizations, state is maintained. The server automatically caches your visualizations — if you reload the page, your visualizations reappear.

<div style={{textAlign: 'center'}}>
  <img width="400" src="https://user-images.githubusercontent.com/19650074/198821344-cb8c424e-455c-4249-b3b4-5554309a5ec7.gif" alt="State Management" />
</div>

- **Save:** You can manually save with the save button. This will serialize the env's state (to disk, in JSON), including window positions. You can save an `env` programmatically. This is helpful for more sophisticated visualizations in which configuration is meaningful, e.g. a data-rich demo, a model training dashboard, or systematic experimentation. This also makes them easy to share and reuse.

- **Fork:** If you enter a new env name, saving will create a new env — effectively **forking** the previous env.

:::tip
Fork an environment before you begin to make edits to ensure that your changes are saved separately.
:::

## Filter

You can use the `filter` to dynamically sift through windows present in an env — just provide a regular expression with which to match titles of windows you want to show. This can be helpful in use cases involving an env with many windows e.g. when systematically checking experimental results.

<div style={{textAlign: 'center'}}>
  <img width="300" src="https://user-images.githubusercontent.com/19650074/198821379-eeebd8a2-bcab-407a-b47f-9b2d0290c23e.png" alt="Filter" />
</div>

:::note
If you have saved your current view, the view will be restored after clearing the filter.
<div style={{textAlign: 'center'}}>
  <img width="500" src="https://user-images.githubusercontent.com/19650074/198821402-4702611e-1038-4093-8cd5-9c8120444211.gif" alt="Filter Restore" />
</div>
:::

## Views

<div style={{textAlign: 'center'}}>
  <img width="300" src="https://user-images.githubusercontent.com/19650074/198821420-458c863b-c304-4d10-8906-0cc2f0c20241.png" alt="Views" />
</div>

It is possible to manage the views simply by dragging the tops of windows around, however additional features exist to keep views organized and save common views. View management can be useful for saving and switching between multiple common organizations of your windows.

### Saving/Deleting Views

Using the folder icon, a dialog window opens where views can be forked in the same way that envs can be. Saving a view will retain the position and sizes of all of the windows in a given environment. Views are saved in `$HOME/.visdom/view/layouts.json` in the visdom filepath.

:::note
Saved views are static, and editing a saved view copies that view over to the `current` view where editing can occur.
:::

### Re-Packing

Using the repack icon (9 boxes), visdom will attempt to pack your windows in a way that they best fit while retaining row/column ordering.

:::note
Due to the reliance on row/column ordering and `ReactGridLayout` the final layout might be slightly different than what might be expected. We're working on improving that experience or providing alternatives that give more fine-tuned control.
:::

### Reloading Views

<div style={{textAlign: 'center'}}>
  <img width="600" src="https://user-images.githubusercontent.com/19650074/198821436-6c7957b5-dd67-4afc-9fc3-4bf074137022.gif" alt="Reloading Views" />
</div>

Using the view dropdown it is possible to select previously saved views, restoring the locations and sizes of all of the windows within the current environment to the places they were when that view was saved last.
