#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Lightning MNIST Demo with Visdom auto-logging
=============================================
Extends the manual example (example/pytorch_mnist_demo.py) to show how
VisdomLogger + GradientNormCallback eliminate all manual viz.line() calls.

Metrics logged automatically
-----------------------------
  train_loss        → logged by LitMNIST.training_step via self.log()
  val_loss          → logged by LitMNIST.validation_step
  val_acc           → logged by LitMNIST.validation_step
  grad_norm         → logged by GradientNormCallback (hook-based)
  grad_hook_ms      → logged by GradientNormCallback when profile_hooks=True

Compare with the manual version:
  # Manual (pytorch_mnist_demo.py):
  viz.line(Y=[loss], X=[epoch], win='loss', update=upd, ...)
  viz.line(Y=[acc],  X=[epoch], win='acc',  update=upd, ...)
  viz.line(Y=[norm], X=[epoch], win='grad_norm', update=upd, ...)

  # Auto (this file):
  # — nothing —  (all handled by logger and callback)

Usage
-----
    python -m visdom.server              # start server first
    python example/demo_lightning_mnist_grad.py
    open http://localhost:8097
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision as tv

# Guard: check for Lightning before proceeding
try:
    import lightning.pytorch as pl
except ImportError:
    try:
        import pytorch_lightning as pl
    except ImportError:
        raise SystemExit(
            "PyTorch Lightning is required for this demo.\n"
            "Install with:  pip install lightning"
        )

from visdom.lightning_logger import GradientNormCallback, VisdomLogger

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BATCH_SIZE = 64
EPOCHS = 5
LR = 1e-3
NUM_WORKERS = 2

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class SimpleCNN(nn.Module):
    """Same LeNet-style CNN as in pytorch_mnist_demo.py."""

    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 32, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        self.fc1 = nn.Linear(64 * 7 * 7, 128)
        self.fc2 = nn.Linear(128, 10)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = x.view(x.size(0), -1)
        x = F.relu(self.fc1(x))
        return self.fc2(x)


# ---------------------------------------------------------------------------
# LightningModule — no manual viz calls needed
# ---------------------------------------------------------------------------


class LitMNIST(pl.LightningModule):
    """
    Wraps SimpleCNN.  All metric logging is done with ``self.log()``, which
    is intercepted by VisdomLogger and forwarded to Visdom automatically.
    """

    def __init__(self, lr: float = LR):
        super().__init__()
        self.save_hyperparameters()  # triggers VisdomLogger.log_hyperparams
        self.model = SimpleCNN()
        self.criterion = nn.CrossEntropyLoss()

    def forward(self, x):
        return self.model(x)

    def training_step(self, batch, batch_idx):
        x, y = batch
        loss = self.criterion(self(x), y)
        # This single call replaces an explicit viz.line() for training loss.
        self.log("train_loss", loss, on_step=False, on_epoch=True, prog_bar=True)
        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = self.criterion(logits, y)
        acc = (logits.argmax(dim=1) == y).float().mean()
        # Both val_loss and val_acc appear in Visdom without any extra code.
        self.log("val_loss", loss, on_epoch=True, prog_bar=True)
        self.log("val_acc", acc, on_epoch=True, prog_bar=True)

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.hparams.lr)
        scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=2, gamma=0.5)
        return {"optimizer": optimizer, "lr_scheduler": scheduler}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def build_dataloaders():
    transform = tv.transforms.Compose(
        [
            tv.transforms.ToTensor(),
            tv.transforms.Normalize((0.5,), (0.5,)),
        ]
    )
    train_ds = tv.datasets.MNIST(
        root="./data", train=True, download=True, transform=transform
    )
    val_ds = tv.datasets.MNIST(
        root="./data", train=False, download=True, transform=transform
    )
    train_dl = torch.utils.data.DataLoader(
        train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=NUM_WORKERS
    )
    val_dl = torch.utils.data.DataLoader(
        val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS
    )
    return train_dl, val_dl


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    train_dl, val_dl = build_dataloaders()

    # VisdomLogger routes every self.log() call to a Visdom line chart.
    logger = VisdomLogger(
        name="mnist_lightning",
        port=8097,
        fail_on_no_connection=True,
    )

    # GradientNormCallback tracks grad norms via autograd hooks — zero
    # boilerplate in the model code.  profile_hooks=True adds timing data.
    grad_cb = GradientNormCallback(
        log_every=50,  # every 50 optimizer steps
        per_layer=True,  # one grad_norm/<param> window per parameter
        profile_hooks=True,  # logs grad_hook_ms to measure overhead
    )

    trainer = pl.Trainer(
        max_epochs=EPOCHS,
        logger=logger,
        callbacks=[grad_cb],
        log_every_n_steps=50,
    )

    model = LitMNIST(lr=LR)
    trainer.fit(model, train_dl, val_dl)

    print(
        "Per-layer norms: each parameter has its own grad_norm/<name> window (per_layer=True)."
    )
    print("\nDashboard: http://localhost:8097")
    print(
        "Windows created:\n"
        "  mnist_lightning-v*/train_loss  — training loss per epoch\n"
        "  mnist_lightning-v*/val_loss    — validation loss per epoch\n"
        "  mnist_lightning-v*/val_acc     — validation accuracy per epoch\n"
        "  mnist_lightning-v*/grad_norm   — gradient norm per step\n"
        "  mnist_lightning-v*/grad_hook_ms — hook overhead (ms)\n"
        "  mnist_lightning-v*/hparams     — hyperparameter table\n"
    )
