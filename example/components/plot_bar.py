import numpy as np

def plot_bar_basic(viz, env, args):
    opts = dict(title=args[0]) if len(args) > 0 else {}
    viz.bar(X=np.random.rand(20), opts=opts, env=env)

def plot_bar_stacked(viz, env, args):
    title = args[0] if len(args) > 0 else None
    viz.bar(
        X=np.abs(np.random.rand(5, 3)),
        opts=dict(
            stacked=True,
            legend=['Facebook', 'Google', 'Twitter'],
            rownames=['2012', '2013', '2014', '2015', '2016'],
            title=title
        ),
        env=env
    )

def plot_bar_nonstacked(viz, env, args):
    title = args[0] if len(args) > 0 else None
    viz.bar(
        X=np.random.rand(20, 3),
        opts=dict(
            stacked=False,
            legend=['The Netherlands', 'France', 'United States'],
            title=title
        ),
        env=env
    )

# histogram
def plot_bar_histogram(viz, env, args):
    title = args[0] if len(args) > 0 else None
    viz.histogram(X=np.random.rand(10000), opts=dict(numbins=20, title=title), env=env)

# pie chart
def plot_bar_piechart(viz, env, args):
    title = args[0] if len(args) > 0 else None
    X = np.asarray([19, 26, 55])
    viz.pie(
        X=X,
        opts=dict(legend=['Residential', 'Non-Residential', 'Utility'], title=title),
        env=env
    )


