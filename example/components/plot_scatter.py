import numpy as np

def plot_scatter_basic(viz, env, args):
    title = args[0] if len(args) > 0 else None
    Y = np.random.rand(100)
    return viz.scatter(
        X=np.random.rand(100, 2),
        Y=(Y[Y > 0] + 1.5).astype(int),
        opts=dict(
            legend=['Didnt', 'Update'],
            xtickmin=-50,
            xtickmax=50,
            xtickstep=0.5,
            ytickmin=-50,
            ytickmax=50,
            ytickstep=0.5,
            markersymbol='cross-thin-open',
            title=title
        ),
        env=env
    )

def plot_scatter_update_opts(viz, env, args):
    old_scatter = plot_scatter_basic(viz, env, args)
    viz.update_window_opts(
        win=old_scatter,
        opts=dict(
            legend=['Apples', 'Pears'],
            xtickmin=0,
            xtickmax=1,
            xtickstep=0.5,
            ytickmin=0,
            ytickmax=1,
            ytickstep=0.5,
            markersymbol='cross-thin-open',
        ),
        env=env
    )

# scatter plot example with various type of updates
def plot_scatter_append(viz, env, args):
    title = args[0] if len(args) > 0 else None
    colors = np.random.randint(0, 255, (2, 3,))
    win = viz.scatter(
        X=np.random.rand(255, 2),
        Y=(np.random.rand(255) + 1.5).astype(int),
        opts=dict(
            markersize=10,
            markercolor=colors,
            legend=['1', '2'],
            title=title
        ),
        env=env
    )

    viz.scatter(
        X=np.random.rand(255),
        Y=np.random.rand(255),
        opts=dict(
            markersize=10,
            markercolor=colors[0].reshape(-1, 3),

        ),
        name='1',
        update='append',
        env=env,
        win=win)

    viz.scatter(
        X=np.random.rand(255, 2),
        Y=(np.random.rand(255) + 1.5).astype(int),
        opts=dict(
            markersize=10,
            markercolor=colors,
        ),
        update='append',
        env=env,
        win=win)



# 3d scatterplot with custom labels and ranges
def plot_scatter_3d(viz, env, args):
    title = args[0] if len(args) > 0 else None
    Y = np.random.rand(100)
    viz.scatter(
        X=np.random.rand(100, 3),
        Y=(Y + 1.5).astype(int),
        opts=dict(
            legend=['Men', 'Women'],
            markersize=5,
            xtickmin=0,
            xtickmax=2,
            xlabel='Arbitrary',
            xtickvals=[0, 0.75, 1.6, 2],
            ytickmin=0,
            ytickmax=2,
            ytickstep=0.5,
            ztickmin=0,
            ztickmax=1,
            ztickstep=0.5,
            title=title
        ),
        env=env
    )

# 2D scatterplot with custom intensities (red channel)
def plot_scatter_custom_marker(viz, env, args):
    title = args[0] if len(args) > 0 else None
    viz.scatter(
        X=np.random.rand(255, 2),
        Y=(np.random.rand(255) + 1.5).astype(int),
        opts=dict(
            markersize=10,
            markercolor=np.random.randint(0, 255, (2, 3,)),
            title=title
        ),
        env=env
    )

# 2D scatter plot with custom colors per label:
def plot_scatter_custom_colors(viz, env, args):
    title = args[0] if len(args) > 0 else None
    viz.scatter(
        X=np.random.rand(255, 2),
        Y=(np.random.randn(255) > 0) + 1,
        opts=dict(
            markersize=10,
            markercolor=np.floor(np.random.random((2, 3)) * 255),
            markerborderwidth=0,
            title=title
        ),
        env=env
    )

def plot_scatter_add_trace(viz, env, args):
    title = args[0] if len(args) > 0 else None
    win = viz.scatter(
        X=np.random.rand(255, 2),
        opts=dict(
            markersize=10,
            markercolor=np.random.randint(0, 255, (255, 3,)),
            title=title
        ),
        env=env
    )

    # assert that the window exists
    assert viz.win_exists(win, env=env), 'Created window marked as not existing'

    # add new trace to scatter plot
    viz.scatter(
        X=np.random.rand(255),
        Y=np.random.rand(255),
        win=win,
        name='new_trace',
        update='new',
        env=env
    )

# 1D scatter plot with text labels:
def plot_scatter_text_labels_1d(viz, env, args):
    title = args[0] if len(args) > 0 else None
    viz.scatter(
        X=np.random.rand(10, 2),
        opts=dict(
            textlabels=['Label %d' % (i + 1) for i in range(10)],
            title=title
        ),
        env=env
    )

# 2D scatter plot with text labels:
def plot_scatter_text_labels_2d(viz, env, args):
    title = args[0] if len(args) > 0 else None
    viz.scatter(
        X=np.random.rand(10, 2),
        Y=[1] * 5 + [2] * 3 + [3] * 2,
        opts=dict(
            legend=['A', 'B', 'C'],
            textlabels=['Label %d' % (i + 1) for i in range(10)],
            title=title
        ),
        env=env
    )


