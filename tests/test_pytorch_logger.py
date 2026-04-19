from __future__ import annotations

import torch

from visdom.integrations.pytorch.logger import VisdomLogger


class DummyVisdom:
    def __init__(self):
        self.calls = []

    def line(self, Y=None, X=None, win=None, env=None, opts=None, update=None):
        if win is None:
            win = f"win_{len(self.calls) + 1}"
        self.calls.append(
            {
                "method": "line",
                "Y": Y,
                "X": X,
                "win": win,
                "env": env,
                "opts": opts,
                "update": update,
            }
        )
        return win

    def heatmap(self, X=None, win=None, env=None, opts=None, update=None):
        if win is None:
            win = f"heatmap_{len(self.calls) + 1}"
        self.calls.append(
            {
                "method": "heatmap",
                "X": X,
                "win": win,
                "env": env,
                "opts": opts,
                "update": update,
            }
        )
        return win

    def histogram(self, X=None, win=None, env=None, opts=None):
        if win is None:
            win = f"hist_{len(self.calls) + 1}"
        self.calls.append(
            {
                "method": "histogram",
                "X": X,
                "win": win,
                "env": env,
                "opts": opts,
            }
        )
        return win


def test_anomaly_warning_is_logged():
    dummy = DummyVisdom()
    logger = VisdomLogger(
        visdom_client=dummy,
        flush_every=1000,
        flush_seconds=999,
        enable_histograms=False,
    )

    logger.log_warning("exploding_grad", 123.0, step=7)
    logger.flush()

    assert any(
        call["method"] == "line" and call["opts"]["title"] == "warning/exploding_grad"
        for call in dummy.calls
    )


def test_auto_log_classification():
    dummy = DummyVisdom()
    logger = VisdomLogger(
        visdom_client=dummy,
        flush_every=1000,
        flush_seconds=999,
        enable_histograms=False,
    )

    outputs = torch.tensor([[2.0, 1.0], [0.1, 0.9]])
    targets = torch.tensor([0, 1])

    logger.auto_log(outputs=outputs, targets=targets, loss=0.25, step=1, group="train")
    logger.flush()

    titles = [call["opts"]["title"] for call in dummy.calls if call["method"] == "line"]
    assert "train/loss" in titles
    assert "train/accuracy" in titles
    assert "train/confidence" in titles


def test_custom_metric_registry():
    dummy = DummyVisdom()
    logger = VisdomLogger(
        visdom_client=dummy,
        flush_every=1000,
        flush_seconds=999,
        enable_histograms=False,
    )

    logger.register_metric("f1_score", lambda outputs, targets: 0.5, group="custom")

    outputs = torch.tensor([[2.0, 1.0], [0.1, 0.9]])
    targets = torch.tensor([0, 1])

    logger.auto_log(outputs=outputs, targets=targets, step=2, group="train")
    logger.flush()

    titles = [call["opts"]["title"] for call in dummy.calls if call["method"] == "line"]
    assert "custom/f1_score" in titles


def test_gradient_hook_anomaly_path():
    dummy = DummyVisdom()
    logger = VisdomLogger(
        visdom_client=dummy,
        flush_every=1000,
        flush_seconds=999,
        enable_histograms=False,
    )

    logger._on_grad("layer.weight", torch.tensor([float("nan"), 1.0]))
    logger.flush()

    titles = [call["opts"]["title"] for call in dummy.calls if call["method"] == "line"]
    assert "warning/nan_grad" in titles