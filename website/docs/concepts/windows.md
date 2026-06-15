---
sidebar_position: 1
title: Windows
description: Understanding Visdom windows — drag, drop, resize, and manage visualizations
---

# Windows

<div style={{textAlign: 'center'}}>
  <img width="500" src="https://user-images.githubusercontent.com/19650074/198821065-6666cb22-d34a-4839-ae19-f6f6a4a1bae4.png" alt="Visdom Windows" />
</div>

Visdom has a simple set of features that can be composed for various use-cases.

The UI begins as a blank slate — you can populate it with plots, images, and text. These appear in windows that you can drag, drop, resize, and destroy. The windows live in `envs` and the state of `envs` is stored across sessions. You can download the content of windows — including your plots in `svg`.

:::tip
You can use the zoom of your browser to adjust the scale of the UI.
:::

## Editable Plot Parameters

Use the top-right *edit* button to inspect all parameters used for a plot in the respective window. The Visdom client supports dynamic change of plot parameters as well. Just change one of the listed parameters, and the plot will be altered on-the-fly. Click the button again to close the property list.

<div style={{textAlign: 'center'}}>
  <img width="400" src="https://user-images.githubusercontent.com/19650074/156751970-0915757d-8bf0-4a6d-a510-1d34a918e47a.gif" alt="Editable Plot Parameters" />
</div>
