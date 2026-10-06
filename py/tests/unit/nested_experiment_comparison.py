#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import pytest

from visdom.experiments import Experiment, build_comparison

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "left,right",
    [
        ([True], [1]),
        ({"enabled": False}, {"enabled": 0}),
        ({"layers": [{"enabled": True}]}, {"layers": [{"enabled": 1}]}),
        ([{"options": [False]}], [{"options": [0.0]}]),
    ],
)
def test_nested_boolean_settings_are_differing(left, right):
    runs = [Experiment("a"), Experiment("b"), Experiment("c")]
    for run, value in zip(runs, [left, right, left]):
        run.set_param("config", value)
    params = build_comparison(runs)["params"]
    assert params["differing"] == ["config"]
    assert params["shared"] == {}
    assert [group["env_ids"] for group in params["groups"]["config"]] == [
        ["a", "c"],
        ["b"],
    ]


@pytest.mark.parametrize(
    "left,right",
    [
        ({"layers": [1, 2.0], "enabled": True}, {"enabled": True, "layers": [1.0, 2]}),
        ([], []),
        ({"value": [float("nan")]}, {"value": [float("nan")]}),
    ],
)
def test_nested_equivalent_settings_are_shared(left, right):
    runs = [Experiment("a"), Experiment("b")]
    for run, value in zip(runs, [left, right]):
        run.set_param("config", value)
    params = build_comparison(runs)["params"]
    assert params["differing"] == []
    assert "config" in params["shared"]
    assert len(params["groups"]["config"]) == 1


@pytest.mark.parametrize(
    "left,right", [([1], [1, 2]), ({"a": 1}, {"b": 1}), ([1, 2], [2, 1]), ([], {})]
)
def test_nested_structure_differences_are_preserved(left, right):
    runs = [Experiment("a"), Experiment("b")]
    for run, value in zip(runs, [left, right]):
        run.set_param("config", value)
    assert build_comparison(runs)["params"]["differing"] == ["config"]
