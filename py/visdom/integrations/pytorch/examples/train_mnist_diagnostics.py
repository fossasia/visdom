from __future__ import annotations

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from visdom.integrations.pytorch import VisdomLogger


class SmallCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(1, 16, 3, 1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, 1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Flatten(),
            nn.Linear(32 * 5 * 5, 128),
            nn.ReLU(),
            nn.Linear(128, 10),
        )

    def forward(self, x):
        return self.net(x)


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_ds = datasets.MNIST(
        root="./data",
        train=True,
        download=True,
        transform=transforms.ToTensor(),
    )
    train_loader = DataLoader(train_ds, batch_size=64, shuffle=True)

    model = SmallCNN().to(device)
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.CrossEntropyLoss()

    SHOW_OPTIONAL_DIAGNOSTICS = True

    logger = VisdomLogger(
        port=8097,
        env="mnist_diagnostics",
        enable_histograms=False,
        enable_model_health=False,
        track_parameter_stats=True,
        show_extra_model_stats=False,
        flush_every=25,
        flush_seconds=2.0,
    )
    logger.attach(model, optimizer)

    global_step = 0
    model.train()

    for epoch in range(2):
        for images, targets in train_loader:
            images = images.to(device)
            targets = targets.to(device)

            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()

            logger.auto_log(
                outputs=outputs.detach(),
                targets=targets.detach(),
                loss=loss.detach(),
                step=global_step,
                group="train",
            )
            
            # 🔥 baseline (ALWAYS log 0)
            logger.log_warning("exploding_grad", 0.0, step=global_step)
            logger.log_warning("nan_grad", 0.0, step=global_step)

            # 🔥 spikes
            if SHOW_OPTIONAL_DIAGNOSTICS and global_step % 200 == 0:
                logger.log_warning("exploding_grad", 15.0, step=global_step)

            if SHOW_OPTIONAL_DIAGNOSTICS and 300 <= global_step < 305:
                logger.log_warning("nan_grad", 5.0, step=global_step)

            logger.log_lr(step=global_step)

            # if SHOW_OPTIONAL_DIAGNOSTICS and global_step % 100 == 0:
            #     logger.log_model_health(step=global_step)

            logger.step(global_step)
            global_step += 1

    logger.close()


if __name__ == "__main__":
    main()