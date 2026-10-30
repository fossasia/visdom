import multiprocessing
import time

import numpy as np

import visdom
from visdom.loggers import VisdomSystemMonitor


def burn(seconds):
    end = time.time() + seconds
    a = np.random.rand(300, 300)
    while time.time() < end:
        a = a @ a
        a /= np.linalg.norm(a)


def main():
    viz = visdom.Visdom()

    # CPU and RAM of this script and its children, sampled every 2 seconds
    with VisdomSystemMonitor(viz, env="system_monitor", interval=2):
        burn(10)

        # RAM grows while the buffer is held
        buffer = np.ones((2000, 2000))
        burn(10)
        del buffer

        # worker processes are summed into the same plots
        workers = [multiprocessing.Process(target=burn, args=(10,)) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        time.sleep(6)


if __name__ == "__main__":
    main()
