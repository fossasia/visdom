#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the client's hierarchy, flow, network and distribution panes.

``sunburst``, ``sankey``, ``graph``, ``violin`` and ``parallel_coordinates``
each assemble a trace by hand rather than going through ``scatter``, so the
payload *is* the contract with the frontend — a renamed key is invisible to
Python and breaks only in the browser.

Two of them are unusual:

* ``graph`` needs ``networkx``, and rejects any edge list whose nodes are not
  numbered 0..n-1, because the frontend indexes nodes positionally.
* ``parallel_coordinates`` runs its trace and layout through ``_scrub_dict``,
  so keys whose value is ``None`` are **removed** rather than sent as null.

Everything here runs through ``capture_send`` against a ``Visdom(send=False)``
client: no server, no I/O.
"""

import sys
from unittest.mock import patch

import numpy as np
import pytest

pytestmark = pytest.mark.unit

requires_assertions = pytest.mark.skipif(
    not __debug__, reason="assert-based validation is stripped under python -O"
)


def trace(sent, index=0):
    """The n-th trace of a captured payload."""
    return sent["payload"]["data"][index]


# -------------------------------------------------------------- sunburst ----


def test_sunburst_sends_labels_and_parents(capture_send):
    sent = capture_send(
        lambda v: v.sunburst(labels=np.array(["a", "b"]), parents=np.array(["", "a"]))
    )
    assert sent["endpoint"] == "events"
    assert trace(sent)["type"] == "sunburst"
    assert trace(sent)["labels"] == ["a", "b"]
    assert trace(sent)["parents"] == ["", "a"]


def test_sunburst_omits_values_when_none_are_given(capture_send):
    """Plotly then sizes each sector by its number of leaves."""
    sent = capture_send(
        lambda v: v.sunburst(labels=np.array(["a"]), parents=np.array([""]))
    )
    assert "values" not in trace(sent)


def test_sunburst_sends_values_when_given(capture_send):
    sent = capture_send(
        lambda v: v.sunburst(
            labels=np.array(["a", "b"]),
            parents=np.array(["", "a"]),
            values=np.array([1, 2]),
        )
    )
    assert trace(sent)["values"] == [1, 2]


def test_sunburst_reads_its_styling_from_opts(capture_send):
    """The four style opts are spelled differently in the trace than in opts."""
    sent = capture_send(
        lambda v: v.sunburst(
            labels=np.array(["a"]),
            parents=np.array([""]),
            opts=dict(size=9, font_color="red", opacity=0.4, marker_width=2),
        )
    )
    assert trace(sent)["outsidetextfont"] == {"size": 9, "color": "red"}
    assert trace(sent)["leaf"] == {"opacity": 0.4}
    assert trace(sent)["marker"] == {"line": {"width": 2}}


def test_sunburst_styling_keys_are_present_but_empty_by_default(capture_send):
    """They are sent as null rather than dropped, unlike parcoords."""
    sent = capture_send(
        lambda v: v.sunburst(labels=np.array(["a"]), parents=np.array([""]))
    )
    assert trace(sent)["outsidetextfont"] == {"size": None, "color": None}
    assert trace(sent)["leaf"] == {"opacity": None}


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            dict(labels=np.array(["a", "b"]), parents=np.array([""])),
            "length of parents and labels should be equal",
        ),
        (
            dict(
                labels=np.array(["a"]),
                parents=np.array([""]),
                values=np.ones((2, 2)),
            ),
            "values should be one-dimensional",
        ),
        (
            dict(
                labels=np.array(["a"]),
                parents=np.array([""]),
                values=np.array([1, 2]),
            ),
            "length of values should be equal",
        ),
    ],
)
def test_sunburst_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.sunburst(**kwargs)


# ---------------------------------------------------------------- sankey ----


def test_sankey_sends_links_as_parallel_index_arrays(capture_send):
    sent = capture_send(lambda v: v.sankey(source=[0, 1], target=[1, 2], value=[1, 2]))
    assert trace(sent)["type"] == "sankey"
    assert trace(sent)["link"] == {"source": [0, 1], "target": [1, 2], "value": [1, 2]}


def test_sankey_defaults_the_node_geometry(capture_send):
    sent = capture_send(lambda v: v.sankey(source=[0], target=[1], value=[1]))
    assert trace(sent)["node"] == {"pad": 15, "thickness": 20}
    assert trace(sent)["orientation"] == "h"


def test_sankey_takes_labels_from_the_argument(capture_send):
    sent = capture_send(
        lambda v: v.sankey(source=[0], target=[1], value=[1], labels=["a", "b"])
    )
    assert trace(sent)["node"]["label"] == ["a", "b"]


def test_sankey_takes_labels_from_opts(capture_send):
    """opts.labels is the documented alternative to the positional argument."""
    sent = capture_send(
        lambda v: v.sankey(
            source=[0], target=[1], value=[1], opts=dict(labels=["a", "b"])
        )
    )
    assert trace(sent)["node"]["label"] == ["a", "b"]


def test_sankey_applies_geometry_orientation_and_colors(capture_send):
    sent = capture_send(
        lambda v: v.sankey(
            source=[0],
            target=[1],
            value=[1],
            opts=dict(
                pad=1, thickness=2, orientation="v", nodecolor="red", linkcolor="blue"
            ),
        )
    )
    assert trace(sent)["orientation"] == "v"
    assert trace(sent)["node"]["pad"] == 1
    assert trace(sent)["node"]["thickness"] == 2
    assert trace(sent)["node"]["color"] == "red"
    assert trace(sent)["link"]["color"] == "blue"


def test_sankey_casts_float_indices_to_integers(capture_send):
    """Plotly indexes nodes with ints; 1.0 from a float array would be invalid."""
    sent = capture_send(
        lambda v: v.sankey(
            source=np.array([0.0]), target=np.array([1.0]), value=np.array([2.5])
        )
    )
    assert trace(sent)["link"]["source"] == [0]
    assert all(isinstance(i, int) for i in trace(sent)["link"]["target"])
    assert trace(sent)["link"]["value"] == [2.5]


def test_sankey_skips_the_label_check_with_no_links(capture_send):
    """An empty diagram references no nodes, so one label is not too few."""
    sent = capture_send(
        lambda v: v.sankey(source=[], target=[], value=[], labels=["a"])
    )
    assert trace(sent)["link"]["source"] == []


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            dict(source=np.ones((2, 2)), target=[0], value=[1]),
            "sankey source must be 1-D",
        ),
        (dict(source=[0, 1], target=[1], value=[1]), "must have the same length"),
        (
            dict(source=[-1], target=[0], value=[1]),
            "source indices must be non-negative",
        ),
        (
            dict(source=[0], target=[-1], value=[1]),
            "target indices must be non-negative",
        ),
        (dict(source=[0.5], target=[1], value=[1]), "source indices must be integers"),
        (dict(source=[0], target=[1.5], value=[1]), "target indices must be integers"),
        (dict(source=[0], target=[1], value=[-1]), "link values must be non-negative"),
        (
            dict(source=[0], target=[1], value=[1], labels=["only-one"]),
            "labels must cover every referenced node",
        ),
        (
            dict(source=[0], target=[1], value=[1], opts=dict(pad=-1)),
            "opts.pad must be a non-negative number",
        ),
        (
            dict(source=[0], target=[1], value=[1], opts=dict(thickness=0)),
            "opts.thickness must be a positive number",
        ),
        (
            dict(source=[0], target=[1], value=[1], opts=dict(orientation="x")),
            "opts.orientation must be",
        ),
    ],
)
def test_sankey_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.sankey(**kwargs)


# ----------------------------------------------------------------- graph ----


def test_graph_sends_a_network_pane(capture_send):
    sent = capture_send(lambda v: v.graph(edges=[(0, 1), (1, 2)]))
    assert sent["endpoint"] == "events"
    assert trace(sent)["type"] == "network"
    assert trace(sent)["content"]["nodes"] == [
        {"name": 0, "label": "0"},
        {"name": 1, "label": "1"},
        {"name": 2, "label": "2"},
    ]
    assert trace(sent)["content"]["edges"] == [
        {"source": 0, "target": 1, "label": "0-1"},
        {"source": 1, "target": 2, "label": "1-2"},
    ]


def test_graph_uses_custom_edge_and_node_labels(capture_send):
    sent = capture_send(
        lambda v: v.graph(
            edges=[(0, 1)], edgeLabels=["flows to"], nodeLabels=["start", "end"]
        )
    )
    assert trace(sent)["content"]["edges"][0]["label"] == "flows to"
    assert [n["label"] for n in trace(sent)["content"]["nodes"]] == ["start", "end"]


def test_graph_colors_nodes_separately_under_the_different_scheme(capture_send):
    """The club index is what the frontend colors on; "same" omits it."""
    sent = capture_send(
        lambda v: v.graph(edges=[(0, 1)], opts=dict(scheme="different"))
    )
    assert [n["club"] for n in trace(sent)["content"]["nodes"]] == [0, 1]


def test_graph_omits_the_club_index_under_the_default_scheme(capture_send):
    sent = capture_send(lambda v: v.graph(edges=[(0, 1)]))
    assert "club" not in trace(sent)["content"]["nodes"][0]


def test_graph_fills_in_its_display_defaults(capture_send):
    sent = capture_send(lambda v: v.graph(edges=[(0, 1)]))
    assert sent["payload"]["opts"] == {
        "directed": False,
        "showVertexLabels": False,
        "showEdgeLabels": False,
        "height": 500,
        "width": 500,
        "scheme": "same",
    }


def test_graph_keeps_the_display_options_it_is_given(capture_send):
    sent = capture_send(
        lambda v: v.graph(
            edges=[(0, 1)],
            opts=dict(directed=True, showVertexLabels=True, height=10, width=20),
        )
    )
    opts = sent["payload"]["opts"]
    assert (opts["directed"], opts["showVertexLabels"]) == (True, True)
    assert (opts["height"], opts["width"]) == (10, 20)


def test_graph_requires_nodes_numbered_from_zero(offline_client):
    """The frontend indexes nodes positionally, so a gap would mislabel them."""
    with pytest.raises(RuntimeError, match="numbered from 0 to n-1"):
        offline_client.graph(edges=[(1, 2)])


def test_graph_reports_a_missing_networkx_as_a_runtime_error(offline_client):
    """The import is deferred, so the failure has to be translated by hand."""
    with patch.dict(sys.modules, {"networkx": None}):
        with pytest.raises(RuntimeError, match="networkx must be installed"):
            offline_client.graph(edges=[(0, 1)])


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(edges=[(0, 1)], edgeLabels=["a", "b"]), "shape of edgeLabels"),
        (dict(edges=[(0, 1)], nodeLabels=["a"]), "length of nodeLabels"),
    ],
)
def test_graph_rejects_label_lists_of_the_wrong_length(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.graph(**kwargs)


# ---------------------------------------------------------------- violin ----


def test_violin_sends_one_trace_per_column(capture_send):
    sent = capture_send(lambda v: v.violin(X=np.array([[1.0, 2.0], [3.0, 4.0]])))
    assert len(sent["payload"]["data"]) == 2
    assert [t["name"] for t in sent["payload"]["data"]] == ["column 0", "column 1"]
    assert trace(sent)["y"] == [1.0, 3.0]
    assert trace(sent, 1)["y"] == [2.0, 4.0]


def test_violin_treats_a_vector_as_a_single_violin(capture_send):
    sent = capture_send(lambda v: v.violin(X=np.array([1.0, 2.0, 3.0])))
    assert len(sent["payload"]["data"]) == 1
    assert trace(sent)["y"] == [1.0, 2.0, 3.0]


def test_violin_squeezes_higher_dimensional_input(capture_send):
    sent = capture_send(lambda v: v.violin(X=np.ones((1, 2, 2))))
    assert len(sent["payload"]["data"]) == 2


def test_violin_defaults_to_a_boxed_vertical_violin(capture_send):
    sent = capture_send(lambda v: v.violin(X=np.array([1.0, 2.0])))
    assert trace(sent)["type"] == "violin"
    assert trace(sent)["box"] == {"visible": True}
    assert trace(sent)["meanline"] == {"visible": True}
    assert trace(sent)["points"] is False
    assert trace(sent)["side"] == "both"
    assert trace(sent)["jitter"] == 0.3
    assert "orientation" not in trace(sent)
    assert "bandwidth" not in trace(sent)


def test_violin_puts_the_data_on_x_when_horizontal(capture_send):
    """A horizontal violin swaps the axis the samples land on."""
    sent = capture_send(
        lambda v: v.violin(X=np.array([1.0, 2.0]), opts=dict(orientation="h"))
    )
    assert trace(sent)["x"] == [1.0, 2.0]
    assert "y" not in trace(sent)
    assert trace(sent)["orientation"] == "h"


def test_violin_names_the_traces_from_the_legend(capture_send):
    sent = capture_send(
        lambda v: v.violin(X=np.array([[1.0, 2.0]]), opts=dict(legend=["train", "val"]))
    )
    assert [t["name"] for t in sent["payload"]["data"]] == ["train", "val"]


def test_violin_applies_the_display_opts(capture_send):
    sent = capture_send(
        lambda v: v.violin(
            X=np.array([1.0, 2.0]),
            opts=dict(
                showbox=False,
                showmeanline=False,
                points="all",
                jitter=0.75,
                side="positive",
                bandwidth=0.5,
                opacity=0.3,
            ),
        )
    )
    assert trace(sent)["box"] == {"visible": False}
    assert trace(sent)["meanline"] == {"visible": False}
    assert trace(sent)["points"] == "all"
    assert trace(sent)["jitter"] == 0.75
    assert trace(sent)["side"] == "positive"
    assert trace(sent)["bandwidth"] == 0.5
    assert trace(sent)["opacity"] == 0.3


def test_violin_omits_jitter_when_it_is_none(capture_send):
    """None means "let Plotly decide", which is not the same as 0."""
    sent = capture_send(
        lambda v: v.violin(X=np.array([1.0, 2.0]), opts=dict(jitter=None))
    )
    assert "jitter" not in trace(sent)


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(X=np.array(1.0)), "X should be one or two-dimensional"),
        (
            dict(X=np.array([[1.0, 2.0]]), opts=dict(legend=["only-one"])),
            "number of legend labels must match",
        ),
        (
            dict(X=np.array([1.0]), opts=dict(orientation="x")),
            "opts.orientation must be",
        ),
        (dict(X=np.array([1.0]), opts=dict(side="up")), "opts.side must be one of"),
        (
            dict(X=np.array([1.0]), opts=dict(points="some")),
            "opts.points must be one of",
        ),
        (dict(X=np.array([1.0]), opts=dict(jitter=2)), "opts.jitter must be a float"),
        (
            dict(X=np.array([1.0]), opts=dict(bandwidth=0)),
            "opts.bandwidth must be a positive number",
        ),
    ],
)
def test_violin_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.violin(**kwargs)


# --------------------------------------------------- parallel_coordinates ----


def test_parallel_coordinates_sends_one_dimension_per_column(capture_send):
    sent = capture_send(
        lambda v: v.parallel_coordinates(X=np.array([[1.0, 2.0], [3.0, 4.0]]))
    )
    assert trace(sent)["type"] == "parcoords"
    dims = trace(sent)["dimensions"]
    assert [d["values"] for d in dims] == [[1.0, 3.0], [2.0, 4.0]]
    assert [d["label"] for d in dims] == ["Dim 1", "Dim 2"]


def test_parallel_coordinates_pads_each_axis_range_by_five_percent(capture_send):
    """Without the padding the extreme lines sit exactly on the axis ends."""
    sent = capture_send(
        lambda v: v.parallel_coordinates(X=np.array([[0.0, 0.0], [10.0, 1.0]]))
    )
    assert trace(sent)["dimensions"][0]["range"] == [-0.5, 10.5]


def test_parallel_coordinates_gives_a_constant_column_a_fixed_range(capture_send):
    """A zero-width range would collapse the axis, so it falls back to +-0.5."""
    sent = capture_send(
        lambda v: v.parallel_coordinates(X=np.array([[1.0, 1.0], [1.0, 2.0]]))
    )
    assert trace(sent)["dimensions"][0]["range"] == [0.5, 1.5]


def test_parallel_coordinates_colors_the_lines_by_y(capture_send):
    sent = capture_send(
        lambda v: v.parallel_coordinates(
            X=np.array([[1.0, 2.0], [3.0, 4.0]]), Y=np.array([0.5, 0.9])
        )
    )
    assert trace(sent)["line"] == {
        "color": [0.5, 0.9],
        "colorscale": "Electric",
        "showscale": True,
        "cmin": 0.5,
        "cmax": 0.9,
    }


def test_parallel_coordinates_drops_the_line_config_without_y(capture_send):
    """_scrub_dict removes the None rather than sending a null Plotly rejects."""
    sent = capture_send(
        lambda v: v.parallel_coordinates(X=np.array([[1.0, 2.0], [3.0, 4.0]]))
    )
    assert "line" not in trace(sent)


def test_parallel_coordinates_reverses_the_colorscale_on_request(capture_send):
    sent = capture_send(
        lambda v: v.parallel_coordinates(
            X=np.array([[1.0, 2.0], [3.0, 4.0]]),
            Y=np.array([1.0, 2.0]),
            opts=dict(colormap="Jet", reversescale=True),
        )
    )
    assert trace(sent)["line"]["colorscale"] == "Jet"
    assert trace(sent)["line"]["reversescale"] is True


def test_parallel_coordinates_takes_labels_ranges_and_ticks_from_opts(capture_send):
    sent = capture_send(
        lambda v: v.parallel_coordinates(
            X=np.array([[1.0, 2.0], [3.0, 4.0]]),
            opts=dict(
                dimensions=["lr", "acc"],
                ranges={0: [0, 10]},
                constraintranges={1: [2, 3]},
                tickvals={0: [1, 3]},
                ticktext={0: ["low", "high"]},
            ),
        )
    )
    first, second = trace(sent)["dimensions"]
    assert first["label"] == "lr"
    assert first["range"] == [0, 10]
    assert first["tickvals"] == [1, 3]
    assert first["ticktext"] == ["low", "high"]
    assert second["constraintrange"] == [2, 3]
    assert "constraintrange" not in first


def test_parallel_coordinates_keeps_the_top_experiments_by_y(capture_send):
    """max_experiments sorts by Y descending, so the worst rows are dropped."""
    sent = capture_send(
        lambda v: v.parallel_coordinates(
            X=np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]),
            Y=np.array([0.1, 0.9, 0.5]),
            opts=dict(max_experiments=2),
        )
    )
    assert trace(sent)["dimensions"][0]["values"] == [3.0, 5.0]
    assert trace(sent)["line"]["color"] == [0.9, 0.5]


def test_parallel_coordinates_leaves_a_short_matrix_alone(capture_send):
    """A cap above the row count must not reorder the experiments."""
    sent = capture_send(
        lambda v: v.parallel_coordinates(
            X=np.array([[1.0, 2.0], [3.0, 4.0]]),
            Y=np.array([0.1, 0.9]),
            opts=dict(max_experiments=5),
        )
    )
    assert trace(sent)["dimensions"][0]["values"] == [1.0, 3.0]


def test_parallel_coordinates_makes_room_for_a_title(capture_send):
    """The title needs the domain to shrink, or it overlaps the axis labels."""
    sent = capture_send(
        lambda v: v.parallel_coordinates(
            X=np.array([[1.0, 2.0]]), opts=dict(title="sweep")
        )
    )
    assert trace(sent)["domain"] == {"y": [0, 0.85]}
    assert sent["payload"]["layout"]["title"] == {
        "text": "sweep",
        "x": 0.5,
        "xanchor": "center",
    }


def test_parallel_coordinates_has_no_domain_without_a_title(capture_send):
    sent = capture_send(lambda v: v.parallel_coordinates(X=np.array([[1.0, 2.0]])))
    assert "domain" not in trace(sent)
    assert "title" not in sent["payload"]["layout"]


def test_parallel_coordinates_forces_a_white_background(capture_send):
    """The default transparent background makes the axis text unreadable."""
    sent = capture_send(lambda v: v.parallel_coordinates(X=np.array([[1.0, 2.0]])))
    assert sent["payload"]["layout"]["paper_bgcolor"] == "white"
    assert sent["payload"]["layout"]["plot_bgcolor"] == "white"


def test_parallel_coordinates_widens_the_pane_with_the_dimension_count(capture_send):
    sent = capture_send(
        lambda v: v.parallel_coordinates(X=np.ones((1, 5)) * np.arange(5))
    )
    assert sent["payload"]["opts"]["width"] == 5 * 140
    assert sent["payload"]["opts"]["height"] == 450


def test_parallel_coordinates_reserves_extra_width_for_the_colorbar(capture_send):
    sent = capture_send(
        lambda v: v.parallel_coordinates(
            X=np.ones((2, 5)) * np.arange(5), Y=np.array([1.0, 2.0])
        )
    )
    assert sent["payload"]["opts"]["width"] == 5 * 140 + 100


def test_parallel_coordinates_rejects_a_single_experiment_with_colors(offline_client):
    """np.squeeze turns a one-element Y into a scalar, which the 1D check refuses.

    A single-row X is otherwise legal, so colouring one experiment is the one
    combination that cannot be plotted.
    """
    with pytest.raises(AssertionError, match="Y must be a 1D vector"):
        offline_client.parallel_coordinates(X=np.array([[1.0, 2.0]]), Y=np.array([1.0]))


def test_parallel_coordinates_never_goes_below_a_readable_width(capture_send):
    sent = capture_send(lambda v: v.parallel_coordinates(X=np.array([[1.0, 2.0]])))
    assert sent["payload"]["opts"]["width"] == 600


def test_parallel_coordinates_keeps_an_explicit_size(capture_send):
    sent = capture_send(
        lambda v: v.parallel_coordinates(
            X=np.array([[1.0, 2.0]]), opts=dict(width=123, height=45)
        )
    )
    assert sent["payload"]["opts"]["width"] == 123
    assert sent["payload"]["opts"]["height"] == 45


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(X=np.ones(3)), "X must be a 2D matrix"),
        (dict(X=np.ones((1, 1))), "at least 2 dimensions"),
        (dict(X=np.ones((2, 2)), Y=np.ones((2, 2))), "Y must be a 1D vector"),
        (dict(X=np.ones((2, 2)), Y=np.ones(3)), "must match number of rows in X"),
        (
            dict(X=np.ones((2, 2)), opts=dict(max_experiments=1)),
            "opts.max_experiments requires Y",
        ),
        (
            dict(X=np.ones((2, 2)), opts=dict(dimensions="ab")),
            "should be a list/tuple of length",
        ),
        (
            dict(X=np.ones((2, 2)), opts=dict(dimensions=["only-one"])),
            "must match number of columns in X",
        ),
        (
            dict(X=np.ones((2, 2)), opts=dict(ticktext={0: ["a"]})),
            r"opts.ticktext\[0\] requires matching opts.tickvals\[0\]",
        ),
        (
            dict(
                X=np.ones((2, 2)),
                opts=dict(tickvals={0: [1]}, ticktext={0: ["a", "b"]}),
            ),
            "must have the same length",
        ),
    ],
)
def test_parallel_coordinates_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.parallel_coordinates(**kwargs)
