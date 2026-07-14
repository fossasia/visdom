import numpy as np


def plot_violin_basic(viz, env, args):
    X = np.random.randn(200)
    viz.violin(
        X=X,
        env=env,
        opts=dict(
            title="Violin Basic",
            legend=["distribution"],
            showbox=True,
            showmeanline=True,
        ),
    )


def plot_violin_multigroup(viz, env, args):
    X = np.column_stack(
        [
            np.random.normal(loc=0.78, scale=0.06, size=300),
            np.random.normal(loc=0.83, scale=0.03, size=300),
            np.random.normal(loc=0.85, scale=0.02, size=300),
            np.random.normal(loc=0.81, scale=0.05, size=300),
        ]
    )
    viz.violin(
        X=X,
        env=env,
        opts=dict(
            title="Val Accuracy by Learning Rate",
            legend=["lr=1e-2", "lr=1e-3", "lr=1e-4", "lr=1e-5"],
            showbox=True,
            showmeanline=True,
            points=False,
        ),
    )


def plot_violin_with_points(viz, env, args):
    X = np.column_stack(
        [
            np.random.exponential(scale=1.8, size=200) + 1.0,
            np.random.exponential(scale=1.0, size=200) + 0.5,
            np.random.exponential(scale=0.5, size=200) + 0.2,
            np.random.exponential(scale=0.25, size=200) + 0.1,
        ]
    )
    viz.violin(
        X=X,
        env=env,
        opts=dict(
            title="Training Loss per Epoch",
            legend=["epoch 1", "epoch 5", "epoch 10", "epoch 20"],
            showbox=True,
            showmeanline=True,
            points="outliers",
            jitter=0.4,
        ),
    )


def plot_violin_horizontal(viz, env, args):
    X = np.column_stack(
        [
            np.random.normal(loc=0.0, scale=1.00, size=400),
            np.random.normal(loc=0.0, scale=0.50, size=400),
            np.random.normal(loc=0.0, scale=0.15, size=400),
            np.random.normal(loc=0.0, scale=0.03, size=400),
            np.random.normal(loc=0.0, scale=0.01, size=400),
        ]
    )
    viz.violin(
        X=X,
        env=env,
        opts=dict(
            title="Violin Layer Activations",
            legend=["layer_1", "layer_2", "layer_3", "layer_4", "layer_5"],
            orientation="h",
            showbox=True,
            showmeanline=True,
        ),
    )
