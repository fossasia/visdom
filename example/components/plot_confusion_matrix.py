#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import numpy as np


def plot_confusion_matrix_basic(viz, env, args):
    np.random.seed(42)
    classes = ["cat", "dog", "bird"]
    n = 300
    y_true = np.random.choice(classes, size=n)
    y_pred = y_true.copy()
    noise_idx = np.random.choice(n, size=n // 4, replace=False)
    y_pred[noise_idx] = np.random.choice(classes, size=len(noise_idx))

    viz.confusion_matrix(
        y_true=y_true,
        y_pred=y_pred,
        opts=dict(title="Confusion Matrix (Basic)"),
        env=env,
    )


def plot_confusion_matrix_precomputed(viz, env, args):
    cm = np.array(
        [
            [50, 2, 3],
            [5, 45, 5],
            [1, 3, 46],
        ]
    )
    labels = ["cat", "dog", "bird"]

    viz.confusion_matrix(
        cm=cm,
        labels=labels,
        opts=dict(title="Confusion Matrix (Precomputed)"),
        env=env,
    )


def plot_confusion_matrix_normalized(viz, env, args):
    np.random.seed(42)
    classes = ["cat", "dog", "bird"]
    n = 300
    y_true = np.random.choice(classes, size=n)
    y_pred = y_true.copy()
    noise_idx = np.random.choice(n, size=n // 4, replace=False)
    y_pred[noise_idx] = np.random.choice(classes, size=len(noise_idx))

    viz.confusion_matrix(
        y_true=y_true,
        y_pred=y_pred,
        normalize="true",
        opts=dict(title="Confusion Matrix (Normalized by Row)"),
        env=env,
    )
