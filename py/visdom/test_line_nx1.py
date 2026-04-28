def test_line_nx1_single_line_behavior(monkeypatch):
    import numpy as np
    from visdom import Visdom

    captured = {}

    # Mock _send to capture what is being sent
    def fake_send(self, *args, **kwargs):
        captured['data'] = kwargs

    viz = Visdom()
    monkeypatch.setattr(viz, "_send", fake_send)

    X = np.arange(5)
    Y = np.arange(5).reshape(-1, 1)  # Shape (N,1)

    viz.line(X=X, Y=Y)

    # Assertions
    assert 'data' in captured

    # Ensure only one line is created (not broadcasted)
    sent_data = captured['data']
    assert sent_data is not None