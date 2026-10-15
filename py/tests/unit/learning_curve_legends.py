# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Named updates must address the traces created with custom legends."""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("update", ["append", "replace", "remove"])
@pytest.mark.parametrize(
    "legend",
    [["Training loss", "Validation loss"], ("Training loss", "Validation loss")],
)
def test_custom_legends_target_existing_learning_curve_traces(
    offline_client, update, legend
):
    opts = {"legend": legend}
    with (
        patch.object(offline_client, "_send", return_value="losses") as send,
        patch.object(offline_client, "win_exists", return_value=True),
    ):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], win="losses", opts=opts
        )
        created = send.call_args.args[0]["data"]
        send.reset_mock()
        offline_client.learning_curve(
            {"train": [0.8], "val": [0.9]},
            step=[1],
            win="losses",
            opts=opts,
            update=update,
        )

    messages = [call.args[0] for call in send.call_args_list]
    assert [message["name"] for message in messages] == [
        trace["name"] for trace in created
    ]
    assert all(message["win"] == "losses" for message in messages)
    assert opts == {"legend": legend}
    if update == "remove":
        assert all(message["delete"] and message["data"] == [] for message in messages)
    else:
        assert [message["data"][0]["name"] for message in messages] == list(legend)
        assert [message["data"][0]["y"] for message in messages] == [[0.8], [0.9]]
        assert all(message["append"] == (update == "append") for message in messages)


def test_default_legends_follow_metric_names_when_update_order_changes(offline_client):
    with (
        patch.object(offline_client, "_send", return_value="losses") as send,
        patch.object(offline_client, "win_exists", return_value=True),
    ):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], win="losses"
        )
        send.reset_mock()
        offline_client.learning_curve(
            {"val": [0.9], "train": [0.8]}, step=[1], win="losses", update="append"
        )
    messages = [call.args[0] for call in send.call_args_list]
    assert [message["name"] for message in messages] == ["val", "train"]
    assert [message["data"][0]["y"] for message in messages] == [[0.9], [0.8]]


@pytest.mark.parametrize("update", ["append", "replace", "remove"])
@pytest.mark.parametrize("metrics", [{"val": [0.9], "train": [0.8]}, {"val": [0.9]}])
def test_metric_keyed_legends_preserve_targets_for_reordered_or_subset_updates(
    offline_client, update, metrics
):
    legend = {"val": "Validation loss", "train": "Training loss"}
    opts = {"legend": legend}
    with (
        patch.object(offline_client, "_send", return_value="losses") as send,
        patch.object(offline_client, "win_exists", return_value=True),
    ):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], win="losses", opts=opts
        )
        assert [trace["name"] for trace in send.call_args.args[0]["data"]] == [
            "Training loss",
            "Validation loss",
        ]
        send.reset_mock()
        offline_client.learning_curve(
            metrics, step=[1], win="losses", opts=opts, update=update
        )

    messages = [call.args[0] for call in send.call_args_list]
    assert [message["name"] for message in messages] == [
        legend[name] for name in metrics
    ]
    if update == "remove":
        assert all(message["delete"] and message["data"] == [] for message in messages)
    else:
        assert [message["data"][0]["y"] for message in messages] == list(
            metrics.values()
        )
        assert all(message["append"] == (update == "append") for message in messages)
    assert opts == {"legend": {"val": "Validation loss", "train": "Training loss"}}


def test_partial_legend_mapping_defaults_to_metric_names(offline_client):
    with patch.object(offline_client, "_send", return_value="losses") as send:
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]},
            opts={"legend": {"train": "Training loss", "unused": "Other"}},
        )
    assert [trace["name"] for trace in send.call_args.args[0]["data"]] == [
        "Training loss",
        "val",
    ]


@pytest.mark.parametrize(
    "legend",
    [{"train": "Loss", "val": "Loss"}, {"train": "val"}],
)
def test_legend_mapping_rejects_ambiguous_trace_names(offline_client, legend):
    with patch.object(offline_client, "_send") as send:
        with pytest.raises(AssertionError, match="unique"):
            offline_client.learning_curve(
                {"train": [1.0], "val": [1.2]}, opts={"legend": legend}
            )
    send.assert_not_called()


def test_legend_mapping_rejects_non_string_labels(offline_client):
    with pytest.raises(AssertionError, match="strings"):
        offline_client.learning_curve(
            {"train": [1.0]}, opts={"legend": {"train": None}}
        )
