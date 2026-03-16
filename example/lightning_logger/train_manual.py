"""
Task 1: Train a simple CNN on MNIST with Visdom logging (manual).

Run the Visdom server first:
    python -m visdom.server -port 8097
Then:
    python train_manual.py
"""
# standard imports ML and NN related
import torch
import torch.nn as nn
import torch.optim as optim
# import visdom for data visualizations
from visdom import Visdom

from model import SimpleCNN
from data import get_loaders


def main():
    # connect to a visdom server on port 8097
    viz = Visdom(port=8097)
    # gpu if avaiable othervise cpu
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # move the weight to the device
    model = SimpleCNN().to(device)
    # chosing the optimizer
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    # choosing the loss function
    criterion = nn.CrossEntropyLoss()

    train_loader, test_loader = get_loaders()

    # train for full 10 full epochs
    for epoch in range(10):
        model.train()
        running_loss = 0.0
        for data, target in train_loader:
            data, target = data.to(device), target.to(device)  # move data and target to the cpu or the gpu
            optimizer.zero_grad()  # clear gradient from previos batch
            loss = criterion(model(data), target)  # compute the loss beetween the data that made trough a forward pass and the target
            loss.backward()  # backpropagation
            optimizer.step()  # weights update
            running_loss += loss.item()  # loss accumulation

        avg_loss = running_loss / len(train_loader)  # average loss acroass the batches
        # as asked by task 1 I do a visdom manual logging.
        # win='loss' identifies which plot window to update. update='append' adds to the existing line
        # rather than replacing it. The opts dict just sets titles and labels.
        viz.line(Y=[avg_loss], X=[epoch], win='loss', update='append',
                 opts=dict(title='training loss', xlabel='epoch', ylabel='loss'))

        # switch to evaluation
        model.eval()
        correct = 0
        # I disable gradient here because I dont need it here
        with torch.no_grad():
            for data, target in test_loader:
                data, target = data.to(device), target.to(device)
                correct += model(data).argmax(1).eq(target).sum().item()
        acc = correct / len(test_loader.dataset)
        # ANOTHER visdom manual logging for accuracy...
        viz.line(Y=[acc], X=[epoch], win='acc', update='append',
                 opts=dict(title='accuracy', xlabel='epoch', ylabel='accuracy'))
        # and ANOTHER visdom manual logging for learning rate...
        viz.line(Y=[optimizer.param_groups[0]['lr']], X=[epoch], win='lr', update='append',
                 opts=dict(title='learning rate', xlabel='epoch', ylabel='LR'))

        print(f"epoch {epoch}: loss={avg_loss:.4f}, acc={acc:.4f}")


if __name__ == "__main__":
    main()
