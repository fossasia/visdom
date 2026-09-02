#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import lightning.pytorch as pl
import torch
from lightning.pytorch.utilities import grad_norm
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

import visdom
from visdom.loggers import VisdomLightningLogger


class Net(pl.LightningModule):
    def __init__(self, lr=1e-2, hidden=32):
        super().__init__()
        self.save_hyperparameters()
        self.net = nn.Sequential(nn.Linear(20, hidden), nn.ReLU(), nn.Linear(hidden, 1))
        self.loss_fn = nn.BCEWithLogitsLoss()

    def forward(self, x):
        return self.net(x).squeeze(-1)

    def _step(self, batch, prefix):
        x, y = batch
        logits = self(x)
        loss = self.loss_fn(logits, y)
        acc = ((logits > 0) == (y > 0.5)).float().mean()
        self.log_dict({"{}_loss".format(prefix): loss, "{}_acc".format(prefix): acc})
        return loss

    def training_step(self, batch, _):
        return self._step(batch, "train")

    def validation_step(self, batch, _):
        self._step(batch, "val")

    def on_before_optimizer_step(self, optimizer):
        # Lightning computes the norms; the logger only plots them.
        self.log_dict(grad_norm(self, norm_type=2))

    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters(), lr=self.hparams.lr)


def main():
    torch.manual_seed(42)
    X = torch.randn(500, 20)
    y = (X[:, :10].sum(dim=1) > 0).float()
    train_loader = DataLoader(TensorDataset(X[:400], y[:400]), batch_size=32)
    val_loader = DataLoader(TensorDataset(X[400:], y[400:]), batch_size=32)

    viz = visdom.Visdom()
    logger = VisdomLightningLogger(viz, env="lightning_run")

    trainer = pl.Trainer(
        max_epochs=20,
        logger=logger,
        log_every_n_steps=5,
        enable_checkpointing=False,
        enable_progress_bar=False,
        enable_model_summary=False,
    )
    trainer.fit(Net(), train_loader, val_loader)


if __name__ == "__main__":
    main()
