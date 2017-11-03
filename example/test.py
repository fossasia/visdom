from visdom import Visdom
import numpy as np
viz = Visdom()


# 2D scatterplot with custom intensities (red channel)
colors = np.random.randint(0, 255, (2, 3,))
win = viz.scatter(
    X=np.random.rand(255, 2),
    Y=(np.random.rand(255) + 1.5).astype(int),
    opts=dict(
        markersize=10,
        markercolor=colors,
    ),
)

a = input("Lets go next.")

viz.scatter(
    X=np.random.rand(255),
    Y=np.random.rand(255),
    opts=dict(
        markersize=10,
        markercolor=np.random.randint(0, 255, (1, 3,)),
    ),
    name='1',
    update='append',
    win=win)

a = input("Lets go next.")
viz.scatter(
    X=np.random.rand(255, 2),
    Y=(np.random.rand(255) + 1.5).astype(int),
    opts=dict(
        markersize=10,
        markercolor=colors,
    ),
    update='append',
    win=win)



# # 2D scatter plot with custom colors per label:
# win = viz.scatter(
#     X=np.random.rand(255, 2),
#     Y=(np.random.randn(255) > 0) + 1,
#     opts=dict(
#         markersize=np.random.randint(6, 20, (255)),
#         markercolor=np.floor(np.random.random((2, 3)) * 255),
#     ),
# )

# win = viz.scatter(
#     X=np.random.rand(255, 2),
#     opts=dict(
#         markersize=10,
#         markercolor=np.random.randint(0, 255, (255, 3,)),
#     ),
# )

# assert that the window exists
# assert viz.win_exists(win)
