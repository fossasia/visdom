import numpy as np

def plot_line_basic(viz, env, args):
    title = args[0] if len(args) > 0 else None
    num = int(args[1]) if len(args) > 1 else 10
    viz.line(Y=np.random.rand(num), opts=dict(showlegend=True, title=title), env=env)

def plot_line_multiple(viz, env, args):
    title = args[0] if len(args) > 0 else None
    Y = np.linspace(-5, 5, 100)
    viz.line(
        Y=np.column_stack((Y * Y, np.sqrt(Y + 5))),
        X=np.column_stack((Y, Y)),
        opts=dict(markers=False, title=title),
        env=env
    )

# line using WebGL
def plot_line_webgl(viz, env, args):
    webgl_num_points = 200000
    webgl_x = np.linspace(-1, 0, webgl_num_points)
    webgl_y = webgl_x**3
    viz.line(X=webgl_x, Y=webgl_y,
             opts=dict(title='{} points using WebGL'.format(webgl_num_points), webgl=True),
             env=env,
             win="WebGL demo")
    return webgl_x

def plot_line_update_webgl(viz, env, args):
    webgl_x = plot_line_webgl(viz, env, args)
    webgl_num_points = len(webgl_x)
    viz.line(
        X=webgl_x+1.,
        Y=(webgl_x+1.)**3,
        win="WebGL demo",
        update='append',
        env=env,
        opts=dict(title='{} points using WebGL'.format(webgl_num_points*2), webgl=True)
    )

# line updates
def plot_line_update(viz, env, args):
    opts = {'title': args[0]} if len(args) > 0 else {}
    win = viz.line(
        X=np.column_stack((np.arange(0, 10), np.arange(0, 10))),
        Y=np.column_stack((np.linspace(5, 10, 10),
                           np.linspace(5, 10, 10) + 5)),
        env=env,
        opts=opts
    )
    viz.line(
        X=np.column_stack((np.arange(10, 20), np.arange(10, 20))),
        Y=np.column_stack((np.linspace(5, 10, 10),
                           np.linspace(5, 10, 10) + 5)),
        env=env,
        win=win,
        update='append'
    )
    viz.line(
        X=np.arange(21, 30),
        Y=np.arange(1, 10),
        env=env,
        win=win,
        name='2',
        update='append'
    )
    viz.line(
        X=np.arange(1, 10),
        Y=np.arange(11, 20),
        env=env,
        win=win,
        name='delete this',
        update='append'
    )
    viz.line(
        X=np.arange(1, 10),
        Y=np.arange(11, 20),
        env=env,
        win=win,
        name='4',
        update='insert'
    )
    viz.line(X=None, Y=None, win=win, name='delete this', update='remove', env=env)


# many small line updates
def plot_line_many_updates(viz, env, args):
    opts = {'title': args[0]} if len(args) > 0 else {}
    win = viz.line(
        X=np.column_stack((np.arange(0, 10), np.arange(0, 10))),
        Y=np.column_stack((np.linspace(5, 10, 10),
                           np.linspace(5, 10, 10) + 5)),
        env=env,
        opts=opts
    )
    for i in range(1,101):
        offset1 = np.random.random() * 100
        offset2 = np.random.random() * 100
        viz.line(
            X=np.column_stack((i * 10 + np.arange(10, 20), i * 10 + np.arange(10, 20))),
            Y=np.column_stack((offset1 + np.linspace(5, 10, 10),
                               offset2 + np.linspace(5, 10, 10))),
            env=env,
            win=win,
            update='append'
        )



def plot_line_opts(viz, env, args):
    return viz.line(
        X=np.column_stack((
            np.arange(0, 10),
            np.arange(0, 10),
            np.arange(0, 10),
        )),
        Y=np.column_stack((
            np.linspace(5, 10, 10),
            np.linspace(5, 10, 10) + 5,
            np.linspace(5, 10, 10) + 10,
        )),
        opts={
            'dash': np.array(['solid', 'dash', 'dashdot']),
            'linecolor': np.array([
                [0, 191, 255],
                [0, 191, 255],
                [255, 0, 0],
            ]),
            'title': 'Different line dash types'
        },
        env=env
    )

def plot_line_opts_update(viz, env, args):
    win = plot_line_opts(viz, env, args)
    viz.line(
        X=np.arange(0, 10),
        Y=np.linspace(5, 10, 10) + 15,
        win=win,
        name='4',
        update='insert',
        opts={
            'linecolor': np.array([
                [255, 0, 0],
            ]),
            'dash': np.array(['dot']),
        },
        env=env
    )

def plot_line_stackedarea(viz, env, args):
    Y = np.linspace(0, 4, 200)
    return viz.line(
        Y=np.column_stack((np.sqrt(Y), np.sqrt(Y) + 2)),
        X=np.column_stack((Y, Y)),
        opts=dict(
            fillarea=True,
            showlegend=False,
            width=800,
            height=800,
            xlabel='Time',
            ylabel='Volume',
            ytype='log',
            title='Stacked area plot',
            marginleft=30,
            marginright=30,
            marginbottom=80,
            margintop=30,
        ),
        env=env
    )

# Assure that the stacked area plot isn't giant
def plot_line_maxsize(viz, env, args):
    win = plot_line_stackedarea(viz, env, args)
    viz.update_window_opts(
        win=win,
        opts=dict(
            width=300,
            height=300,
        ),
        env=env
    )


# double y axis plot
def plot_line_doubleyaxis(viz, env, args):
    opts = {'title': args[0]} if len(args) > 0 else {}
    X = np.arange(20)
    Y1 = np.random.randint(0, 20, 20)
    Y2 = np.random.randint(0, 20, 20)
    viz.dual_axis_lines(X, Y1, Y2, env=env, opts=opts)



# PyTorch tensor
def plot_line_pytorch(viz, env, args):
    try:
        import torch
        viz.line(Y=torch.Tensor([[0., 0.], [1., 1.]]), env=env)
    except ImportError:
        print('Skipped PyTorch example')

# stemplot
def plot_line_stem(viz, env, args):
    title = args[0] if len(args) > 0 else None
    Y = np.linspace(0, 2 * np.pi, 70)
    X = np.column_stack((np.sin(Y), np.cos(Y)))
    viz.stem(
        X=X,
        Y=Y,
        opts=dict(legend=['Sine', 'Cosine'], title=title),
        env=env
    )
