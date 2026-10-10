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
