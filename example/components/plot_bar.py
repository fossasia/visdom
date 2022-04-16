import numpy as np

def plot_bar_basic(viz, env):
    viz.bar(X=np.random.rand(20))

def plot_bar_stacked(viz, env):
    viz.bar(
        X=np.abs(np.random.rand(5, 3)),
        opts=dict(
            stacked=True,
            legend=['Facebook', 'Google', 'Twitter'],
            rownames=['2012', '2013', '2014', '2015', '2016']
        )
    )

def plot_bar_nonstacked(viz, env):
    viz.bar(
        X=np.random.rand(20, 3),
        opts=dict(
            stacked=False,
            legend=['The Netherlands', 'France', 'United States']
        )
    )

# histogram
def plot_bar_histogram(viz, env):
    viz.histogram(X=np.random.rand(10000), opts=dict(numbins=20))

# pie chart
def plot_bar_piechart(viz, env):
    X = np.asarray([19, 26, 55])
    viz.pie(
        X=X,
        opts=dict(legend=['Residential', 'Non-Residential', 'Utility'])
    )


