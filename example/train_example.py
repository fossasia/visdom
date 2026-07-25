import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset, random_split

import visdom
from visdom.pytorch import VisdomLogger


class MLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(20, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, 4),
        )

    def forward(self, x):
        return self.net(x)


def main():
    torch.manual_seed(42)

    # synthetic 4-class classification: 1000 samples, 20 features
    X = torch.randn(1000, 20)
    y = torch.randint(0, 4, (1000,))

    dataset = TensorDataset(X, y)
    train_set, val_set = random_split(dataset, [800, 200])
    train_loader = DataLoader(train_set, batch_size=32, shuffle=True)
    val_loader   = DataLoader(val_set,   batch_size=64)

    model     = MLP()
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=1e-2)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.5)

    viz = visdom.Visdom()

    with VisdomLogger(viz, env="mlp_run") as tracker:
        for epoch in range(50):

            # training
            model.train()
            train_losses, train_accs = [], []
            for inputs, targets in train_loader:
                outputs = model(inputs)
                loss    = criterion(outputs, targets)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                preds = outputs.argmax(dim=1)
                train_losses.append(loss.item())
                train_accs.append((preds == targets).float().mean().item())

            # validation
            model.eval()
            val_losses, val_accs = [], []
            with torch.no_grad():
                for inputs, targets in val_loader:
                    outputs = model(inputs)
                    loss    = criterion(outputs, targets)
                    preds   = outputs.argmax(dim=1)
                    val_losses.append(loss.item())
                    val_accs.append((preds == targets).float().mean().item())

            train_loss = sum(train_losses) / len(train_losses)
            train_acc  = sum(train_accs)   / len(train_accs)
            val_loss   = sum(val_losses)   / len(val_losses)
            val_acc    = sum(val_accs)     / len(val_accs)

            tracker.log("Train Loss",     train_loss)
            tracker.log("Train Accuracy", train_acc)
            tracker.log("Learning Rate",  optimizer.param_groups[0]["lr"])
            tracker.log("Val Loss",       val_loss)
            tracker.log("Val Accuracy",   val_acc)

            scheduler.step()

            print(
                "epoch {:02d}  train_loss={:.4f}  val_loss={:.4f}  val_acc={:.4f}".format(
                    epoch + 1, train_loss, val_loss, val_acc,
                )
            )


if __name__ == "__main__":
    main()
