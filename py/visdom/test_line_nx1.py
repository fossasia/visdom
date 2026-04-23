import numpy as np
from visdom import Visdom

def test_line_nx1_does_not_crash():
    viz = Visdom(server="http://localhost", raise_exceptions=False)

    X = np.linspace(0, 10, 5)
    Y = np.random.rand(5, 1)

    viz.line(Y=Y, X=X, opts=dict(title="Nx1 test"))