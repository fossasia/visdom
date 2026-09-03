import numpy as np


# boxplot
def plot_special_boxplot(viz, env, args):
    title = args[0] if len(args) > 0 else None
    X = np.random.rand(100, 2)
    X[:, 1] += 2
    viz.boxplot(X=X, opts=dict(legend=["Men", "Women"], title=title), env=env)


# quiver plot
def plot_special_quiver(viz, env, args):
    X = np.arange(0, 2.1, 0.2)
    Y = np.arange(0, 2.1, 0.2)
    X = np.broadcast_to(np.expand_dims(X, axis=1), (len(X), len(X)))
    Y = np.broadcast_to(np.expand_dims(Y, axis=0), (len(Y), len(Y)))
    U = np.multiply(np.cos(X), Y)
    V = np.multiply(np.sin(X), Y)
    viz.quiver(X=U, Y=V, opts=dict(normalize=0.9), env=env)


# mesh plot
def plot_special_mesh(viz, env, args):
    x = [0, 0, 1, 1, 0, 0, 1, 1]
    y = [0, 1, 1, 0, 0, 1, 1, 0]
    z = [0, 0, 0, 0, 1, 1, 1, 1]
    X = np.c_[x, y, z]
    i = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2]
    j = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3]
    k = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6]
    Y = np.c_[i, j, k]
    viz.mesh(X=X, Y=Y, opts=dict(opacity=0.5), env=env)


# sunburst (hierarchy) chart
def plot_special_sunburst(viz, env, args):
    labels = np.array(["A", "B", "C", "D", "E"])
    parents = np.array(["", "A", "A", "B", "B"])
    values = np.array([5, 3, 2, 1, 1])
    viz.sunburst(labels, parents, values, opts=dict(title="Sunburst"), env=env)


# plot network graph
def plot_special_graph(viz, env, args):
    edges = [(0, 1), (0, 2), (1, 3), (1, 4), (1, 5), (4, 5)]
    edgeLabels = ["A", "B", "C", "D", "E", "F"]  # in the order of edges
    nodeLabels = ["Orange", "Mango", "Apple", "Grapes", "Papaya", "kiwi"]

    viz.graph(
        edges,
        edgeLabels,
        nodeLabels,
        opts={
            "showEdgeLabels": True,
            "showVertexLabels": True,
            "scheme": "different",
            "directed": False,
        },
        env=env,
    )


# parallel coordinates plot
def plot_special_parallel_coordinates(viz, env, args):
    n = 20
    X = np.column_stack(
        [
            np.random.uniform(1e-4, 0.1, n),
            np.random.choice([16, 32, 64, 128, 256], n).astype(float),
            np.random.randint(10, 200, n).astype(float),
            np.random.uniform(0.0, 0.5, n),
            np.random.uniform(1e-5, 1e-2, n),
            np.random.choice([0, 1, 2], n).astype(float),
            np.random.choice([64, 128, 256, 512], n).astype(float),
            np.random.uniform(50, 99, n),
            np.random.uniform(0.01, 1.0, n),
            np.random.uniform(0.4, 0.95, n),
        ]
    )
    viz.parallel_coordinates(
        X=X,
        Y=X[:, 7],
        env=env,
        opts=dict(
            dimensions=[
                "LR",
                "Batch",
                "Epochs",
                "Dropout",
                "WD",
                "Optim",
                "Hidden",
                "Acc",
                "Loss",
                "F1",
            ],
            title="Experiment Comparison",
            tickvals={5: [0, 1, 2]},
            ticktext={5: ["SGD", "Adam", "AdamW"]},
        ),
    )


# sankey (flow) diagram
def plot_special_sankey(viz, env, args):
    title = args[0] if len(args) > 0 else None
    labels = ["raw", "cleaned", "labeled", "train", "val", "test"]
    source = [0, 1, 2, 2, 2]
    target = [1, 2, 3, 4, 5]
    value = [1000, 900, 720, 144, 36]
    viz.sankey(
        source=source,
        target=target,
        value=value,
        labels=labels,
        opts=dict(title=title),
        env=env,
    )
