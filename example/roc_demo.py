"""
Simple ROC demo for Visdom

This script generates synthetic binary labels and scores, sends a ROC
curve to the running Visdom server using the newly added `Visdom.roc`
API, and also saves a local PNG screenshot of the ROC to the user's
Downloads folder for convenience.

Run while the Visdom server is running (e.g. `python -m visdom.server`).
"""
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

from visdom import Visdom


def compute_roc(y_true, y_score):
    y_true = np.asarray(y_true).astype(int)
    y_score = np.asarray(y_score)
    desc = np.argsort(-y_score)
    y_sorted = y_true[desc]
    P = y_true.sum()
    N = y_true.shape[0] - P
    tp = np.cumsum(y_sorted)
    fp = np.cumsum(1 - y_sorted)
    tpr = np.concatenate(([0.0], tp / float(P)))
    fpr = np.concatenate(([0.0], fp / float(N)))
    return fpr, tpr


def main():
    # Synthetic example
    rng = np.random.RandomState(0)
    y_true = rng.randint(0, 2, size=200)
    # create separable-ish scores
    y_score = y_true * (0.6 + 0.4 * rng.rand(y_true.shape[0])) + (1 - y_true) * (0.4 * rng.rand(y_true.shape[0]))

    vis = Visdom()
    # send to visdom server
    vis.roc(y_true, y_score, win="roc_demo", name="demo")

    # also save a local PNG to Downloads
    fpr, tpr = compute_roc(y_true, y_score)
    plt.figure(figsize=(6, 6))
    plt.plot(fpr, tpr, marker=".", label="demo")
    plt.plot([0, 1], [0, 1], linestyle="--", color="gray")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title("ROC Curve (demo)")
    plt.legend()
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    out = downloads / "visdom_roc_demo.png"
    plt.savefig(out, bbox_inches="tight")
    print(f"Saved ROC PNG to {out}")


if __name__ == "__main__":
    main()
