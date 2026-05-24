#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Demo: Visdom Logging Bridge
============================

This script demonstrates the two main logging utilities:

1. **VisdomLoggingHandler** — context manager / decorator for vanilla PyTorch
   training loops (no Lightning dependency).
2. **VisdomLogger** — PyTorch Lightning ``Logger`` subclass (requires
   ``pytorch_lightning``).

Start a Visdom server before running this script::

    python -m visdom.server

Then run::

    python example/demo_logging.py
"""

import math
import argparse
import numpy as np


def demo_handler(server, port):
    """Demonstrate VisdomLoggingHandler with a simulated training loop."""
    from visdom.logging import VisdomLoggingHandler

    print("\n=== VisdomLoggingHandler Demo ===")
    print("Simulating a 50-epoch training loop ...\n")

    with VisdomLoggingHandler(server=server, port=port, env="handler_demo") as logger:
        for epoch in range(50):
            # Simulated metrics (decaying loss, increasing accuracy).
            loss = 2.0 * math.exp(-0.05 * epoch) + 0.1 * np.random.randn()
            accuracy = 1.0 - math.exp(-0.04 * epoch) + 0.02 * np.random.randn()
            lr = 0.001 * (0.95**epoch)

            logger.log(
                {"train/loss": loss, "train/accuracy": accuracy, "lr": lr},
                step=epoch,
            )

        logger.log_text("<h3>Training complete!</h3><p>50 epochs finished.</p>")

    print("Done! Check environment 'handler_demo' in your browser.\n")


def demo_handler_decorator(server, port):
    """Demonstrate VisdomLoggingHandler as a decorator."""
    from visdom.logging import VisdomLoggingHandler

    print("=== VisdomLoggingHandler Decorator Demo ===")
    print("Running decorated training function ...\n")

    @VisdomLoggingHandler(server=server, port=port, env="decorator_demo")
    def train(logger):
        for step in range(30):
            loss = 1.5 * math.exp(-0.1 * step) + 0.05 * np.random.randn()
            logger.log({"loss": loss}, step=step)
        return "finished"

    result = train()
    print("Decorator returned: {}\n".format(result))


def demo_handler_filtering(server, port):
    """Demonstrate include/exclude metric filtering."""
    from visdom.logging import VisdomLoggingHandler

    print("=== Metric Filtering Demo ===")
    print("Only 'loss' and 'accuracy' will be logged (lr excluded) ...\n")

    with VisdomLoggingHandler(
        server=server,
        port=port,
        env="filter_demo",
        include_metrics=["loss", "acc*"],
    ) as logger:
        for epoch in range(20):
            logger.log(
                {
                    "loss": 1.0 / (epoch + 1),
                    "accuracy": epoch / 20.0,
                    "lr": 0.001,  # will be filtered out
                },
                step=epoch,
            )

    print("Done! Only loss and accuracy windows should appear.\n")


def demo_lightning_logger(server, port):
    """Demonstrate VisdomLogger (Lightning Logger subclass)."""
    try:
        from visdom.logging import VisdomLogger
    except ImportError:
        print(
            "=== VisdomLogger Demo ===\n"
            "Skipped: pytorch_lightning is not installed.\n"
            "Install with: pip install pytorch-lightning\n"
        )
        return

    print("=== VisdomLogger Demo ===")
    print("Simulating Lightning-style log_metrics calls ...\n")

    logger = VisdomLogger(
        server=server,
        port=port,
        env="lightning_demo",
    )

    # Simulate what Lightning would do internally.
    logger.log_hyperparams(
        {"lr": 0.001, "batch_size": 64, "optimizer": "Adam", "epochs": 100}
    )

    for step in range(40):
        metrics = {
            "train_loss": 3.0 * math.exp(-0.08 * step) + 0.1 * np.random.randn(),
            "val_loss": 3.5 * math.exp(-0.06 * step) + 0.15 * np.random.randn(),
            "val_acc": 1.0 - math.exp(-0.05 * step) + 0.02 * np.random.randn(),
        }
        logger.log_metrics(metrics, step=step)

    logger.finalize("success")
    print("Done! Check environment '{}' in your browser.\n".format(logger._env))


def demo_auto_versioning(server, port):
    """Demonstrate automatic environment versioning across runs."""
    from visdom.logging import VisdomLoggingHandler
    from visdom.logging._version import get_next_version
    from visdom import Visdom

    print("=== Auto-Versioning Demo ===")

    viz = Visdom(
        server=server,
        port=port,
        env="main",
        raise_exceptions=False,
        use_incoming_socket=False,
    )
    env_name, version = get_next_version(viz, "versioned_run")
    print("Next version: {} (version {})\n".format(env_name, version))

    with VisdomLoggingHandler(server=server, port=port, env=env_name) as logger:
        for step in range(15):
            logger.log({"metric": np.sin(step / 3.0)}, step=step)

    print(
        "Logged to environment '{}'. Run again to see version increment!\n".format(
            env_name
        )
    )


if __name__ == "__main__":
    DEFAULT_PORT = 8097
    DEFAULT_HOSTNAME = "http://localhost"

    parser = argparse.ArgumentParser(description="Visdom Logging Bridge Demo")
    parser.add_argument(
        "-port",
        type=int,
        default=DEFAULT_PORT,
        help="Port the Visdom server is running on (default: {})".format(DEFAULT_PORT),
    )
    parser.add_argument(
        "-server",
        type=str,
        default=DEFAULT_HOSTNAME,
        help="Server address (default: {})".format(DEFAULT_HOSTNAME),
    )
    FLAGS = parser.parse_args()

    print("Visdom Logging Bridge Demo")
    print("=" * 40)
    print("Server: {}:{}".format(FLAGS.server, FLAGS.port))

    demo_handler(FLAGS.server, FLAGS.port)
    demo_handler_decorator(FLAGS.server, FLAGS.port)
    demo_handler_filtering(FLAGS.server, FLAGS.port)
    demo_auto_versioning(FLAGS.server, FLAGS.port)
    demo_lightning_logger(FLAGS.server, FLAGS.port)

    print("All demos complete!")
