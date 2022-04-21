import numpy as np

# boxplot
def plot_special_boxplot(viz, env, args):
    title = args[0] if len(args) > 0 else None
    X = np.random.rand(100, 2)
    X[:, 1] += 2
    viz.boxplot(
        X=X,
        opts=dict(legend=['Men', 'Women'], title=title),
        env=env
    )

# quiver plot
def plot_special_quiver(viz, env, args):
    X = np.arange(0, 2.1, .2)
    Y = np.arange(0, 2.1, .2)
    X = np.broadcast_to(np.expand_dims(X, axis=1), (len(X), len(X)))
    Y = np.broadcast_to(np.expand_dims(Y, axis=0), (len(Y), len(Y)))
    U = np.multiply(np.cos(X), Y)
    V = np.multiply(np.sin(X), Y)
    viz.quiver(
        X=U,
        Y=V,
        opts=dict(normalize=0.9),
        env=env
    )

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

# plot network graph
def plot_special_graph(viz, env, args):
    edges = [(0,1),(0,2),(1,3),(1,4),(1,5),(4,5)]
    edgeLabels = [ "A", "B", "C", "D", "E", "F"]    # in the order of edges
    nodeLabels = ["Orange", "Mango", "Apple", "Grapes", "Papaya","kiwi"]
    
    viz.graph(edges, edgeLabels, nodeLabels, opts = {"showEdgeLabels" : True, "showVertexLabels" : True, "scheme" : "different", "directed" : False}, env=env)


