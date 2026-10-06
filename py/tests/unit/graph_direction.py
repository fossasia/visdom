# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Directed network graphs retain each requested link's direction."""

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "edges",
    [[(0, 1), (1, 0)], [(0, 1), (1, 2), (2, 0)], [(2, 1), (0, 2), (1, 0)]],
)
def test_directed_graph_preserves_link_directions(capture_send, edges):
    sent = capture_send(lambda client: client.graph(edges, opts={"directed": True}))
    content = sent["payload"]["data"][0]["content"]
    actual = {(edge["source"], edge["target"]) for edge in content["edges"]}
    assert actual == set(edges)
    assert sent["payload"]["opts"]["directed"] is True
    assert [node["name"] for node in content["nodes"]] == list(
        range(len(content["nodes"]))
    )


def test_reciprocal_directed_edges_accept_both_labels(capture_send):
    sent = capture_send(
        lambda client: client.graph(
            [(0, 1), (1, 0)], edgeLabels=["forward", "back"], opts={"directed": True}
        )
    )
    edges = sent["payload"]["data"][0]["content"]["edges"]
    assert [(edge["source"], edge["target"], edge["label"]) for edge in edges] == [
        (0, 1, "forward"),
        (1, 0, "back"),
    ]


@pytest.mark.parametrize("opts", [None, {"directed": False}])
def test_undirected_graph_still_collapses_reciprocal_edges(capture_send, opts):
    sent = capture_send(lambda client: client.graph([(0, 1), (1, 0)], opts=opts))
    edges = sent["payload"]["data"][0]["content"]["edges"]
    assert len(edges) == 1
    assert {edges[0]["source"], edges[0]["target"]} == {0, 1}
    assert sent["payload"]["opts"]["directed"] is False


def test_directed_labels_follow_input_edges_not_node_groups(capture_send):
    requested = [(0, 1), (2, 3), (1, 2), (0, 3)]
    labels = ["first", "second", "third", "fourth"]
    sent = capture_send(
        lambda client: client.graph(
            requested, edgeLabels=labels, opts={"directed": True}
        )
    )
    edges = sent["payload"]["data"][0]["content"]["edges"]
    assert [(edge["source"], edge["target"], edge["label"]) for edge in edges] == [
        (source, target, label) for (source, target), label in zip(requested, labels)
    ]


def test_directed_duplicate_edges_keep_first_seen_unique_order(capture_send):
    sent = capture_send(
        lambda client: client.graph(
            iter([(1, 0), (0, 1), (1, 0)]),
            edgeLabels=["back", "forward"],
            opts={"directed": True},
        )
    )
    edges = sent["payload"]["data"][0]["content"]["edges"]
    assert [(edge["source"], edge["target"], edge["label"]) for edge in edges] == [
        (1, 0, "back"),
        (0, 1, "forward"),
    ]
