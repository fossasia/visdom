import numpy as np

def plot_surface_basic(viz, env, withnames=False):
    columnnames = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'] if withnames else None
    rownames = ['y1', 'y2', 'y3', 'y4', 'y5'] if withnames else None
    return viz.heatmap(
        X=np.outer(np.arange(1, 6), np.arange(1, 11)),
        opts=dict(
            columnnames=columnnames,
            rownames=rownames,
        ),
        env=env
    )

def plot_surface_basic_withnames(viz, env, args):
    plot_surface_basic(viz, env, True)

def plot_surface_append(viz, env, withnames=False):
    win = plot_surface_basic(viz, env, withnames)
    viz.heatmap(
        X=np.outer(np.arange(6, 9), np.arange(1, 11)),
        win=win,
        update='appendRow',
        opts=dict(
            rownames=['y6', 'y7', 'y8'] if withnames else None
        ),
        env=env
    )
    viz.heatmap(
        X=np.outer(np.arange(1, 9), np.arange(11, 14)),
        win=win,
        update='appendColumn',
        opts=dict(
            columnnames=['c1', 'c2', 'c3'] if withnames else None,
            colormap='Rainbow'
        ),
        env=env
    )
    viz.heatmap(
        X=np.outer(np.arange(-1, 1), np.arange(1, 14)),
        win=win,
        update='prependRow',
        opts=dict(
            rownames=['y-', 'y0'] if withnames else None,
        ),
        env=env
    )
    viz.heatmap(
        X=np.outer(np.arange(-1, 9), np.arange(-5, 1)),
        win=win,
        update='prependColumn',
        opts=dict(
            columnnames=['c4', 'c5', 'c6', 'c7', 'c8', 'c9'] if withnames else None,
            colormap='Electric'
        ),
        env=env
    )
    return win

def plot_surface_append_withnames(viz, env, args):
    plot_surface_append(viz, env, True)

def plot_surface_remove(viz, env, withnames=False):
    win = plot_surface_append(viz, env, withnames)
    win = viz.heatmap(
        X=None,
        win=win,
        update="remove",
        env=env
    )

def plot_surface_remove_withnames(viz, env, args):
    plot_surface_remove(viz, env, True)

def plot_surface_replace(viz, env, withnames=False):
    win = plot_surface_append(viz, env, withnames)
    win = viz.heatmap(
        X=10*np.outer(np.arange(1, 20), np.arange(1, 25)),
        win=win,
        update="replace",
        env=env
    )

def plot_surface_replace_withnames(viz, env, args):
    plot_surface_replace(viz, env, True)

# contour
def plot_surface_contour(viz, env, args):
    x = np.tile(np.arange(1, 101), (100, 1))
    y = x.transpose()
    X = np.exp((((x - 50) ** 2) + ((y - 50) ** 2)) / -(20.0 ** 2))
    viz.contour(X=X, opts=dict(colormap='Viridis'), env=env)

# surface
def plot_surface_3d(viz, env, args):
    x = np.tile(np.arange(1, 101), (100, 1))
    y = x.transpose()
    X = np.exp((((x - 50) ** 2) + ((y - 50) ** 2)) / -(20.0 ** 2))
    viz.surf(X=X, opts=dict(colormap='Hot'), env=env)


