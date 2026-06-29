---
sidebar_position: 2
title: Environments
description: Partition your visualization space with environments
---

# Environments

<div style={{textAlign: 'center'}}>
  <img width="300" src="https://user-images.githubusercontent.com/19650074/198821281-ea1cea1a-66c3-495e-be52-cd0f1a3300f7.png" alt="Environments" />
</div>

You can partition your visualization space with `envs`. By default, every user will have an env called `main`. New envs can be created in the UI or programmatically. The state of envs is persistently saved. Environments are able to keep entirely different pools of plots.

You can access a specific env via url: `http://localhost:8097/env/main`. If your server is hosted, you can share this url so others can see your visualizations too.

Environments are automatically hierarchically organized by the first `_`. Note that `/` characters in environment names are escaped to `_`, so both `_` and `/` can affect how environments appear hierarchically in the UI.

## Selecting Environments

<div style={{textAlign: 'center'}}>
  <img width="300" src="https://user-images.githubusercontent.com/19650074/198821299-6602d557-7a02-4b9f-b1d5-d57615cdc15c.png" alt="Selecting Environments" />
</div>

From the main page it is possible to toggle between different environments using the environment selector. Selecting a new environment will query the server for the plots that exist in that environment. The environment selector allows for searching and filtering for the new environment.

## Comparing Environments

From the main page it is possible to compare different environments using the environment selector. Selecting multiple environments in the check box will query the server for the plots with the same titles in all environments and plot them in a single plot. An additional compare legend pane is created with a number corresponding to each selected environment. Individual plots are updated with legends corresponding to "x_name" where `x` is a number corresponding with the compare legend pane and `name` is the original name in the legend.

:::note
The compare envs view is not robust to high throughput data, as the server is responsible for generating the compared content. Do not compare an environment that is receiving a high quantity of updates on any plot, as every update will request regenerating the comparison. If you need to compare two plots that are receiving high quantities of data, have them share the same window on a singular env.
:::

## Clearing Environments

You can use the eraser button to remove all of the current contents of an environment. This closes the plot windows for that environment but keeps the empty environment for new plots.

## Managing Environments

<div style={{textAlign: 'center'}}>
  <img width="400" src="https://user-images.githubusercontent.com/19650074/198821309-4c6449fd-978a-462a-aa35-e59d872b61bd.png" alt="Managing Environments" />
</div>

Pressing the folder icon opens a dialog that allows you to fork or force save the current environment, or delete any of your existing environments. Use of this feature is fully described in the [Views and Filters](./views-and-filters.md) section.

:::info Env Files
Your envs are loaded upon request by the user, by default from `$HOME/.visdom/`. Custom paths can be passed as a cmd-line argument. Envs are removed by using the delete button or by deleting the corresponding `.json` file from the env dir. In case you want the server to pre-load all files into cache, use the flag `-eager_data_loading`.
:::
