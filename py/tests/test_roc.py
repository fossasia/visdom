import types
import numpy as np
import pytest

from visdom import Visdom


def test_roc_calls_line_and_values():
    # Create a Visdom instance without running __init__ to avoid network
    vis = Visdom.__new__(Visdom)

    captured = {}

    def fake_line(Y, X=None, win=None, env=None, opts=None, name=None):
        # capture the inputs for assertions
        captured["Y"] = np.asarray(Y)
        captured["X"] = np.asarray(X)
        captured["win"] = win
        captured["env"] = env
        captured["opts"] = opts
        captured["name"] = name
        return "ok"

    vis.line = fake_line

    # simple synthetic data
    y_true = np.array([0, 0, 1, 1])
    y_score = np.array([0.1, 0.4, 0.35, 0.8])

    res = Visdom.roc(vis, y_true, y_score, win="w", env="e", name="n")
    assert res == "ok"

    # Expected FPR/TPR computation
    # sort descending scores -> indices [3,1,2,0]
    # y_sorted = [1,0,1,0]
    # tp_cum = [1,1,2,2] -> tpr = [0, 1/2, 1/2, 1, 1] after prepend
    # fp_cum = [0,1,1,2] -> fpr = [0, 0/2, 1/2, 1/2, 1]
    assert "Y" in captured and "X" in captured
    Y = captured["Y"]
    X = captured["X"]
    assert np.isclose(Y[0], 0.0) and np.isclose(X[0], 0.0)
    assert Y.shape[0] == X.shape[0]


def test_roc_requires_both_classes():
    vis = Visdom.__new__(Visdom)
    vis.line = lambda *args, **kwargs: None

    y_true_all_pos = np.ones(5)
    y_score = np.linspace(0, 1, 5)

    with pytest.raises(AssertionError):
        Visdom.roc(vis, y_true_all_pos, y_score)
