"""
Task 3: Train the CNN via PyTorch Lightning with the custom VisdomLogger.

Run the Visdom server first:
    python -m visdom.server -port 8097
Then:
    python train_lightning.py
"""
import torch.nn as nn
import torch.optim as optim
import lightning.pytorch as pl

from model import SimpleCNN
from data import get_loaders
from visdom_logger import VisdomLogger


# wrapping the model in a lightning module
class MNISTModel(pl.LightningModule):
    def __init__(self):
        super().__init__()
        self.model = SimpleCNN()  # reuse the same CNN from task 1
        self.criterion = nn.CrossEntropyLoss()

    # as task 1 we defined how data flows through
    def forward(self, x):
        return self.model(x)

    # lightning handle for each batch zero_grad(), backward(), optimizer.step()
    def training_step(self, batch, batch_idx):
        x, y = batch
        loss = self.criterion(self(x), y)
        self.log("train_loss", loss)
        return loss

    # as task 1 we definte the validation_step
    def validation_step(self, batch, batch_idx):
        x, y = batch
        pred = self(x).argmax(1)
        acc = pred.eq(y).float().mean()
        self.log("val_acc", acc)  # one line, no viz.line() boilerplate

    # as task 1 we define the optimizer
    def configure_optimizers(self):
        return optim.Adam(self.parameters(), lr=1e-3)


def main():
    train_loader, test_loader = get_loaders()

    # create the logger, create the trainer and hand it to the logger
    logger = VisdomLogger(port=8097)
    trainer = pl.Trainer(max_epochs=5, logger=logger)
    trainer.fit(
        MNISTModel(),
        train_dataloaders=train_loader,
        val_dataloaders=test_loader,
    )


if __name__ == "__main__":
    main()
