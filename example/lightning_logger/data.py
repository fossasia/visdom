"""
MNIST data loading shared across scripts.
"""
from torchvision import datasets, transforms
from torch.utils.data import DataLoader


def get_loaders(train_batch_size=64, test_batch_size=1000, data_dir="./data"):
    # normalization for stable training
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,)),
    ])
    # load the training set (in batches)
    train_loader = DataLoader(
        datasets.MNIST(data_dir, train=True, download=True, transform=transform),
        batch_size=train_batch_size, shuffle=True,
    )
    # load the evaluation set (not need to be in batches)
    test_loader = DataLoader(
        datasets.MNIST(data_dir, train=False, transform=transform),
        batch_size=test_batch_size,
    )
    return train_loader, test_loader
