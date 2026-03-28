import os
import torch
from torch import nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
import pytorch_lightning as pl

# Import the logger we just wired up in __init__.py!
from visdom import VisdomLogger


class LitMNIST(pl.LightningModule):
    def __init__(self):
        super().__init__()
        # A simple MLP for speed
        self.l1 = nn.Linear(28 * 28, 64)
        self.l2 = nn.Linear(64, 10)

    def forward(self, x):
        x = x.view(x.size(0), -1)
        x = torch.relu(self.l1(x))
        x = self.l2(x)
        return x

    def training_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = F.cross_entropy(logits, y)

        self.log("train_loss", loss)

        return loss

    def on_before_optimizer_step(self, optimizer):
        # We ensure env is set so it appears in 'lightning_mnist' with the other plots
        current_env = self.logger.env

        if not hasattr(self, "grad_win"):
            self.grad_win = self.logger.experiment.plot_grad_norm(
                model=self, step=self.global_step, env=current_env
            )
        else:
            self.logger.experiment.plot_grad_norm(
                model=self,
                step=self.global_step,
                win=self.grad_win,
                env=current_env,
                update="append",
            )

    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters(), lr=1e-3)


if __name__ == "__main__":
    # 1. Prepare Data
    transform = transforms.Compose(
        [transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))]
    )
    dataset = datasets.MNIST(
        os.getcwd(), train=True, download=True, transform=transform
    )
    train_loader = DataLoader(dataset, batch_size=64)

    # 2. Setup Logger
    print("Initializing VisdomLogger...")
    # We put this in a separate environment to keep things clean
    vis_logger = VisdomLogger(env="lightning_mnist")

    # 3. Setup Trainer
    model = LitMNIST()
    trainer = pl.Trainer(
        logger=vis_logger,
        max_epochs=1,
        log_every_n_steps=10,  # Calls your log_metrics() every 10 batches
    )

    # 4. Train
    print("Starting training. Open http://localhost:8097")
    trainer.fit(model, train_loader)
