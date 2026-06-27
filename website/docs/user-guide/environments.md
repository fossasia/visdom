---
sidebar_position: 3
title: Managing Environments
description: Organize your visualizations into separate workspaces
---

# Managing Environments

Environments are Visdom's way of organizing visualizations into separate, named workspaces. Each environment is an independent collection of windows that is saved and restored across sessions.

<div style={{textAlign: 'center'}}>
  <img width="300" src="https://user-images.githubusercontent.com/19650074/198821281-ea1cea1a-66c3-495e-be52-cd0f1a3300f7.png" alt="Environments" />
</div>

## Default environment

Every Visdom server starts with a `main` environment. If you don't specify an environment, all visualizations go here:

```python
import visdom
vis = visdom.Visdom()  # uses env='main' by default

vis.text('This is in the main environment')
```

## Creating environments

Create a new environment by specifying `env` when constructing the client or on individual calls:

```python
# All calls from this client go to 'experiment_lr_001'
vis = visdom.Visdom(env='experiment_lr_001')
vis.line(Y=[1, 2, 3], X=[1, 2, 3], opts=dict(title='Loss'))

# Or specify per-call
vis2 = visdom.Visdom()
vis2.text('Hello', env='experiment_lr_002')
vis2.text('World', env='experiment_lr_003')
```

## Accessing environments

Each environment is accessible via URL:

```
http://localhost:8097/env/experiment_lr_001
```

Share this URL with collaborators to let them view your visualizations.

## Selecting environments in the UI

<div style={{textAlign: 'center'}}>
  <img width="300" src="https://user-images.githubusercontent.com/19650074/198821299-6602d557-7a02-4b9f-b1d5-d57615cdc15c.png" alt="Environment Selector" />
</div>

Use the environment selector dropdown in the top-left of the dashboard to switch between environments. It supports searching and filtering by name.

## Hierarchical naming

Environments are automatically grouped hierarchically using `_` as a separator:

```python
# These will appear nested in the UI under "experiment"
vis.text('A', env='experiment_resnet')
vis.text('B', env='experiment_vgg')
vis.text('C', env='experiment_transformer')
```

:::note
Forward slashes `/` in environment names are converted to `_`, so both affect the hierarchy the same way.
:::

## Comparing environments

You can compare multiple environments side by side. In the UI, select multiple environments using the checkboxes — Visdom will overlay plots with matching titles from each environment.

This is useful for comparing different training runs:

```python
# Run 1
vis1 = visdom.Visdom(env='run_baseline')
vis1.line(Y=losses_baseline, X=epochs, opts=dict(title='Loss'))

# Run 2
vis2 = visdom.Visdom(env='run_augmented')
vis2.line(Y=losses_augmented, X=epochs, opts=dict(title='Loss'))
```

Now select both environments in the UI to see the loss curves overlaid.

:::caution
Avoid comparing environments that receive high-throughput updates — the server regenerates comparison content on every update.
:::

## Saving environments

Environments are saved automatically to `$HOME/.visdom/`. You can also save explicitly:

```python
vis.save(['experiment_lr_001', 'experiment_lr_002'])
```

Or click the **save** button (💾) in the UI.

## Forking environments

Create a copy of an existing environment:

```python
vis.fork_env('experiment_lr_001', 'experiment_lr_001_backup')
```

Or use the folder icon in the UI and type a new name.

:::tip
Fork an environment before making changes to preserve the original state.
:::

## Managing environments in the UI

<div style={{textAlign: 'center'}}>
  <img width="400" src="https://user-images.githubusercontent.com/19650074/198821309-4c6449fd-978a-462a-aa35-e59d872b61bd.png" alt="Managing Environments" />
</div>

Click the folder icon to open the environment manager. From here you can:

- **Fork** — create a copy with a new name
- **Save** — persist the current state
- **Delete** — remove an environment permanently

## Clearing & deleting

```python
# Close all windows in an environment (keeps the empty env)
vis.close(env='experiment_lr_001')

# Delete an environment entirely (IRREVERSIBLE)
vis.delete_env('experiment_lr_001')
```

In the UI, use the **eraser** button to clear all windows, or the environment manager to delete.

## Listing environments

```python
envs = vis.get_env_list()
print(envs)
# ['main', 'experiment_lr_001', 'experiment_lr_002']
```

## Environment files

Environment state is stored as JSON files in `$HOME/.visdom/`:

```
~/.visdom/
├── main.json
├── experiment_lr_001.json
├── experiment_lr_002.json
└── view/
    └── layouts.json
```

You can back up, share, or delete environments by copying or removing these files. Use `-env_path` to customize the storage directory:

```bash
visdom -env_path /data/visdom_envs
```

Use `-eager_data_loading` to pre-load all environments into cache on startup (default: lazy loading on first access).
