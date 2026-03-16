"""
Task 2: Inspect the Lightning Logger interface to understand the methods
a custom logger must implement.

Usage:
    python explore_logger.py
"""
import lightning.pytorch as pl
from lightning.pytorch.loggers import Logger  # it's a blueprint that defines what methods a logger must have
import inspect  # its important to inspect what is inside other class, specifically in Logger

# inspect all the method inside the Logger, this is part of understanding the logger interface for task 2
for name, method in inspect.getmembers(Logger, predicate=inspect.isfunction):
    if not name.startswith('_'):
        sig = inspect.signature(method)
        print(f"{name}{sig}")
