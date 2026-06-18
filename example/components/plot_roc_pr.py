import numpy as np


def plot_roc_curve(viz, env, args):
    np.random.seed(42)
    n = 200
    y_true = np.concatenate([np.zeros(n // 2), np.ones(n // 2)])
    y_score = np.random.rand(n)
    y_score[y_true == 1] += 0.5
    y_score = np.clip(y_score, 0, 1)

    viz.roc_curve(
        y_true=y_true,
        y_score=y_score,
        opts=dict(title='ROC Curve Example'),
        env=env,
    )


def plot_pr_curve(viz, env, args):
    np.random.seed(42)
    n = 200
    y_true = np.concatenate([np.zeros(n // 2), np.ones(n // 2)])
    y_score = np.random.rand(n)
    y_score[y_true == 1] += 0.5
    y_score = np.clip(y_score, 0, 1)

    viz.pr_curve(
        y_true=y_true,
        y_score=y_score,
        opts=dict(title='PR Curve Example'),
        env=env,
    )


def plot_roc_precomputed(viz, env, args):
    fpr = np.array([0.0, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0])
    tpr = np.array([0.0, 0.4, 0.6, 0.75, 0.85, 0.92, 0.97, 1.0])

    viz.roc_curve(
        fpr=fpr,
        tpr=tpr,
        opts=dict(title='ROC Curve (Precomputed)'),
        env=env,
    )
