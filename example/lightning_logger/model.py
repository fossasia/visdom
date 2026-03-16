"""
Shared model definitions used across all scripts.
"""
import torch
import torch.nn as nn


# simple CNN to build for task 1, with 2 convolutional layer, 1 fully connected layer and 1 output layer:
class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 32, 3, 1)
        self.conv2 = nn.Conv2d(32, 64, 3, 1)
        self.fc1 = nn.Linear(9216, 128)
        self.fc2 = nn.Linear(128, 10)

    # forward pass defining the how data flows along the network:
    def forward(self, x):
        x = torch.relu(self.conv1(x))
        x = torch.relu(self.conv2(x))
        x = torch.max_pool2d(x, 2)
        x = torch.flatten(x, 1)
        x = torch.relu(self.fc1(x))
        return self.fc2(x)


# we consider a big and deep model for make noticible the eventual slow down of implementation with lightning
class BigModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(*[nn.Linear(512, 512) for _ in range(20)])

    def forward(self, x):
        return self.layers(x)
