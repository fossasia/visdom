"""
Task 5: Train the CNN while monitoring gradient norms via Visdom.

Run the Visdom server first:
    python -m visdom.server -port 8097
Then:
    python train_gradient_monitor.py
"""
import torch
import torch.nn as nn
import torch.optim as optim

from model import SimpleCNN
from data import get_loaders
from gradient_logger import GradientNormLogger


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = SimpleCNN().to(device)
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.CrossEntropyLoss()

    train_loader, _ = get_loaders()

    # installs all the hooks on the model
    grad_logger = GradientNormLogger(model, log_every=50)

    for epoch in range(2):
        model.train()
        for data, target in train_loader:
            data, target = data.to(device), target.to(device)
            optimizer.zero_grad()
            loss = criterion(model(data), target)
            loss.backward()
            optimizer.step()
            grad_logger.on_step()
        print(f"Epoch {epoch}: loss={loss.item():.4f}")

    # always clean up hooks when done
    grad_logger.detach()
    print("ok, all gradient norms were logged to visdom")


if __name__ == "__main__":
    main()
