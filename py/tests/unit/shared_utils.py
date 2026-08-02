#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for ``visdom.utils.shared_utils``.

These helpers sit under every JSON response the server writes and every plot
payload the client builds, but nothing in the suite exercised them directly.
Two of them are subtle enough to be worth pinning down explicitly:

* ``_sanitize_nans`` changes *shape* as well as values — a tuple comes back as
  a list — because JSON has no tuple.
* ``warn_once`` dedupes against a module-level set, so a warning raised by one
  test silently suppresses the same warning in another. ``conftest.py`` carries
  an autouse fixture for that; the paired tests below are what prove it works.
"""

import io
import json
import math
import os
import uuid
import warnings

import numpy as np
import pytest

from visdom.utils import shared_utils
from visdom.utils.shared_utils import (
    NanSafeEncoder,
    _coerce_image_slider_index,
    _is_missing_value,
    _sanitize_nans,
    ensure_dir_exists,
    get_new_window_id,
    get_rand_id,
    get_visdom_path,
    warn_once,
)

pytestmark = pytest.mark.unit


# -- _sanitize_nans ----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        np.float32("nan"),
        np.float64("inf"),
        np.float64("-inf"),
    ],
)
def test_sanitize_replaces_non_finite_floats(value):
    """NaN and both infinities become None, whatever float type carries them."""
    assert _sanitize_nans(value) is None


@pytest.mark.parametrize(
    "value",
    [0, -1, 3.5, np.float64(2.5), "text", "", None, True, False, b"bytes"],
)
def test_sanitize_leaves_everything_else_alone(value):
    """Finite numbers, strings, booleans and None pass through untouched."""
    assert _sanitize_nans(value) == value


def test_sanitize_recurses_through_nested_containers():
    """Non-finite values are replaced at any depth, inside dicts and lists."""
    payload = {
        "data": [{"y": [1.0, float("nan"), 3.0]}],
        "layout": {"yaxis": {"range": [float("-inf"), float("inf")]}},
        "title": "keep me",
    }
    assert _sanitize_nans(payload) == {
        "data": [{"y": [1.0, None, 3.0]}],
        "layout": {"yaxis": {"range": [None, None]}},
        "title": "keep me",
    }


def test_sanitize_coerces_tuples_to_lists():
    """Tuples come back as lists — JSON has no tuple, so the shape changes."""
    result = _sanitize_nans((1.0, float("nan")))
    assert result == [1.0, None]
    assert isinstance(result, list)


def test_sanitize_coerces_nested_tuples():
    """The tuple coercion applies at every level, including dict values."""
    result = _sanitize_nans({"pairs": [(1, 2), (3, 4)]})
    assert result == {"pairs": [[1, 2], [3, 4]]}


def test_sanitize_leaves_ndarrays_untouched():
    """An ndarray is not a list, so it is returned as-is for the encoder to reject."""
    array = np.array([1.0, np.nan])
    assert _sanitize_nans(array) is array


# -- NanSafeEncoder ----------------------------------------------------------


def test_encoder_writes_null_not_nan():
    """dumps() emits JSON null, never the non-standard NaN/Infinity tokens."""
    payload = {"y": [1.0, float("nan"), float("inf"), float("-inf")]}
    encoded = json.dumps(payload, cls=NanSafeEncoder)
    assert "NaN" not in encoded
    assert "Infinity" not in encoded
    assert json.loads(encoded) == {"y": [1.0, None, None, None]}


def test_encoder_covers_the_streaming_path():
    """dump() to a stream goes through iterencode, which is patched separately."""
    stream = io.StringIO()
    json.dump({"y": [float("nan")]}, stream, cls=NanSafeEncoder)
    assert json.loads(stream.getvalue()) == {"y": [None]}


def test_encoder_round_trips_ordinary_payloads():
    """A payload with nothing to sanitise survives unchanged."""
    payload = {"data": [{"x": [1, 2], "y": [3.5, 4.5], "type": "scatter"}]}
    assert json.loads(json.dumps(payload, cls=NanSafeEncoder)) == payload


def test_default_encoder_still_emits_nan():
    """The plain encoder does not do this, which is why NanSafeEncoder exists."""
    assert "NaN" in json.dumps({"y": [float("nan")]})


# -- _is_missing_value -------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [None, float("nan"), float("inf"), float("-inf"), np.float32("nan")],
)
def test_missing_value_detects_gaps(value):
    """Clients mark a gap in a series with None, NaN or Inf."""
    assert _is_missing_value(value) is True


@pytest.mark.parametrize(
    "value",
    [0, 0.0, -1, "", "cat", "2026-01-01", [], {}, np.int64(3), np.float64(1.5), False],
)
def test_missing_value_treats_everything_else_as_present(value):
    """Categorical strings and falsy-but-real values are present, not gaps.

    Passing a string to ``math.isnan`` raises ``TypeError``; guarding on the
    numeric types instead is what keeps a categorical x-axis from 500ing.
    """
    assert _is_missing_value(value) is False


# -- warn_once ---------------------------------------------------------------


def _prime(message, warningtype=None):
    """Record ``message`` as already seen, without leaking it to the report."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        warn_once(message, warningtype)


def test_warn_once_warns_the_first_time():
    """The first call with a given message raises the warning."""
    with pytest.warns(UserWarning, match="first sighting"):
        warn_once("first sighting")


def test_warn_once_is_silent_the_second_time():
    """A repeat of the same message is suppressed."""
    _prime("repeated message")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_once("repeated message")
    assert caught == []


def test_warn_once_still_warns_for_a_different_message():
    """Deduplication is per message, not global."""
    _prime("message A")
    with pytest.warns(UserWarning, match="message B"):
        warn_once("message B")


def test_warn_once_honours_the_warning_type():
    """The requested category reaches the warnings machinery."""
    with pytest.warns(DeprecationWarning, match="going away"):
        warn_once("going away", DeprecationWarning)


def test_reset_fixture_isolates_a_message_part_one():
    """Raise a warning that the next test raises again (see part two)."""
    with pytest.warns(UserWarning, match="shared between tests"):
        warn_once("shared between tests")


def test_reset_fixture_isolates_a_message_part_two():
    """The same message must warn again: reset_warn_once cleared the set.

    Without the autouse fixture in ``conftest.py`` this fails, and only when the
    two tests run in this order — the failure mode the fixture exists to stop.
    """
    with pytest.warns(UserWarning, match="shared between tests"):
        warn_once("shared between tests")


def test_reset_fixture_restores_preexisting_entries():
    """Messages seen before the suite started are put back after each test."""
    assert isinstance(shared_utils._seen_warnings, set)
    _prime("recorded in the module global")
    assert "recorded in the module global" in shared_utils._seen_warnings


# -- path helpers ------------------------------------------------------------


def test_visdom_path_is_the_package_directory():
    """With no argument the package's own directory is returned."""
    import visdom

    assert get_visdom_path() == os.path.dirname(visdom.__file__)


def test_visdom_path_joins_a_relative_asset():
    """A filename is joined onto the package directory."""
    assert get_visdom_path("static") == os.path.join(get_visdom_path(), "static")


def test_visdom_path_resolves_a_real_asset():
    """The join points at something that actually ships with the package."""
    assert os.path.isdir(get_visdom_path("static"))


def test_ensure_dir_creates_missing_parents(tmp_path):
    """Intermediate directories are created, not just the leaf."""
    target = tmp_path / "envs" / "view" / "nested"
    ensure_dir_exists(str(target))
    assert target.is_dir()


def test_ensure_dir_is_idempotent(tmp_path):
    """Calling it on an existing directory is a no-op, not an error."""
    ensure_dir_exists(str(tmp_path))
    ensure_dir_exists(str(tmp_path))
    assert tmp_path.is_dir()


def test_ensure_dir_keeps_existing_contents(tmp_path):
    """An existing directory is left alone, contents included."""
    (tmp_path / "main.json").write_text("{}")
    ensure_dir_exists(str(tmp_path))
    assert (tmp_path / "main.json").read_text() == "{}"


# -- id helpers --------------------------------------------------------------


def test_rand_id_is_a_uuid():
    """get_rand_id returns a parseable UUID string."""
    uuid.UUID(get_rand_id())


def test_rand_ids_are_distinct():
    """Two calls never collide."""
    assert get_rand_id() != get_rand_id()


def test_new_window_id_is_prefixed():
    """Window ids carry the window_ prefix over a UUID."""
    win = get_new_window_id()
    assert win.startswith("window_")
    uuid.UUID(win[len("window_") :])


# -- _coerce_image_slider_index ----------------------------------------------


@pytest.mark.parametrize(
    "index,expected",
    [
        (3, 3),
        (0, 0),
        (-2, -2),
        (2.0, 2),
        (np.int32(4), 4),
        (np.float64(5.0), 5),
        (np.array([6]), 6),
    ],
)
def test_slider_index_normalises_to_int(index, expected):
    """Whole numbers of any numeric flavour become a plain int."""
    result = _coerce_image_slider_index(index)
    assert result == expected
    assert type(result) is int


@pytest.mark.parametrize("index", [True, False, "3", None, [3]])
def test_slider_index_rejects_non_numbers(index):
    """Booleans and non-numerics are a TypeError, not a silent int()."""
    with pytest.raises(TypeError):
        _coerce_image_slider_index(index)


@pytest.mark.parametrize("index", [2.5, float("nan"), float("inf")])
def test_slider_index_rejects_unusable_floats(index):
    """A fractional or non-finite float cannot name a frame."""
    with pytest.raises(ValueError):
        _coerce_image_slider_index(index)


def test_slider_index_rejects_multi_element_arrays():
    """An array has to hold exactly one value to be an index."""
    with pytest.raises(TypeError):
        _coerce_image_slider_index(np.array([1, 2]))


def test_math_isnan_would_raise_on_a_string():
    """Documents why _is_missing_value guards on type before calling isnan."""
    with pytest.raises(TypeError):
        math.isnan("cat")
