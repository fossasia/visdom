import visdom
import numpy as np
vis = visdom.Visdom(env='test')
for i in range(5):
    vis.scatter(np.random.random((50,2)),win=i)
vis.save(['test'])
