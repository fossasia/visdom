---
sidebar_position: 1
title: Introduction
description: Visdom — creating, organizing & sharing visualizations of live, rich data
slug: /
---

# Introduction

Creating, organizing & sharing visualizations of live, rich data. Supports [Python](https://pypi.org/project/visdom/).

[![GitHub Release](https://img.shields.io/github/v/release/fossasia/visdom?colorA=363a4f&colorB=a6da95&style=for-the-badge)](https://github.com/fossasia/visdom/releases)
[![PyPI Downloads](https://img.shields.io/pypi/dd/visdom?colorA=363a4f&colorB=156df1&style=for-the-badge)](https://pypi.org/project/visdom)
[![Commit Activity](https://img.shields.io/github/commit-activity/m/fossasia/visdom?colorA=363a4f&colorB=0099ff&style=for-the-badge)](https://github.com/fossasia/visdom/commits)
[![Contributors](https://img.shields.io/github/contributors/fossasia/visdom?colorA=363a4f&colorB=60b9f4&style=for-the-badge)](https://github.com/fossasia/visdom/contributors)

Visdom aims to facilitate visualization of (remote) data with an emphasis on supporting scientific experimentation. Broadcast visualizations of plots, images, and text for yourself and your collaborators. Organize your visualization space programmatically or through the UI to create dashboards for live data, inspect results of experiments, or debug experimental code.

![Visdom Dashboard](https://user-images.githubusercontent.com/19650074/198747904-7a8a580f-851a-45fb-8f45-94e54a910ee2.png)

<div style={{display: 'flex', gap: '1%'}}>
  <img width="49.5%" src="https://user-images.githubusercontent.com/19650074/198748177-c973f387-c392-4f6e-9e3d-27dfe578eb59.gif" alt="Visdom Demo" />
  <img width="49.5%" src="https://user-images.githubusercontent.com/19650074/198748189-917091b6-95c4-4415-b965-ba3e7e81e1f8.png" alt="Visdom Plots" />
</div>

## Quick Start

```bash
pip install visdom
visdom
```

Then navigate to `http://localhost:8097` in your browser.

## What's Next?

- [Installation](./getting-started/installation.md) — detailed setup instructions
- [Usage](./getting-started/usage.md) — start the server and create your first visualization
- [Concepts](./concepts/windows.md) — learn about windows, environments, and more
- [API Reference](./api/overview.md) — full API documentation
