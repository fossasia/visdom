def test_line_nx1_single_line_behavior(monkeypatch):
    import numpy as np
    from visdom import Visdom

    captured = {}

    def fake_send(self, msg, *args, **kwargs):
        captured["msg"] = msg
        return True

    monkeypatch.setattr(Visdom, "_send", fake_send)

    viz = Visdom(send=False, use_incoming_socket=False)

    X = np.arange(5)
    Y = np.arange(5).reshape(-1, 1)

    viz.line(X=X, Y=Y)

    assert "msg" in captured

    sent_data = captured["msg"]["data"]

    # Ensure only one trace with N points
    assert len(sent_data) == 5