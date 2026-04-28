import numpy as np
from visdom import Visdom


def test_line_nx1_does_not_crash(monkeypatch):
    viz = Visdom(raise_exceptions=False)

    # Mock _send to avoid real network calls
    monkeypatch.setattr(viz, "_send", lambda *args, **kwargs: True)

    X = np.arange(5)
    Y = np.random.rand(5, 1)

    result = viz.line(X=X, Y=Y)

    assert result is not None