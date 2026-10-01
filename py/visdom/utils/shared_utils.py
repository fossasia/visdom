#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Utilities that could be potentially useful in various different
parts of the visdom stack. Not to be used for particularly specific
helper functions.
"""

import importlib
import json
import math
import numbers
import uuid
import warnings
import os

import numpy as np

_seen_warnings = set()


def warn_once(msg, warningtype=None):
    """
    Raise a warning, but only once.
    :param str msg: Message to display
    :param Warning warningtype: Type of warning, e.g. DeprecationWarning
    """
    global _seen_warnings
    if msg not in _seen_warnings:
        _seen_warnings.add(msg)
        warnings.warn(msg, warningtype, stacklevel=2)


def get_rand_id():
    """Returns a random id string"""
    return str(uuid.uuid4())


def get_new_window_id():
    """Return a string to be used for a new window"""
    return f"window_{get_rand_id()}"


def ensure_dir_exists(path):
    """Make sure the dir exists so we can write a file."""
    os.makedirs(os.path.abspath(path), exist_ok=True)


def get_visdom_path(filename=None):
    """Get the path to an asset."""
    cwd = os.path.dirname(importlib.util.find_spec("visdom").origin)
    if filename is None:
        return cwd
    return os.path.join(cwd, filename)


def _coerce_image_slider_index(index):
    """Validate and normalize a slider index to a plain Python int."""
    if isinstance(index, np.ndarray):
        if index.size != 1:
            raise TypeError("image slider index must be a single integer value")
        index = index.item()
    elif isinstance(index, np.generic):
        index = index.item()

    if isinstance(index, bool):
        raise TypeError("image slider index must be an integer, got bool")

    if isinstance(index, numbers.Integral):
        return int(index)

    if isinstance(index, numbers.Real):
        if not math.isfinite(index):
            raise ValueError("image slider index must be finite")
        if float(index).is_integer():
            return int(index)
        raise ValueError(
            "image slider index must be an integer, got {!r}".format(index)
        )

    raise TypeError(
        "image slider index must be an integer, got {}".format(type(index).__name__)
    )


def _table_cell_to_native(cell):
    """Coerce a single table cell/header to a JSON-serializable native
    type. Handles numpy scalars that json.dumps and NanSafeEncoder cannot
    serialize on their own.
    """
    if isinstance(cell, np.generic):
        cell = cell.item()
    if cell is None or isinstance(cell, (str, int, float, bool)):
        return cell
    return str(cell)


def _normalize_table_data(data, headers):
    """Shared normalization/validation for tabular data, currently
    used by both `table()` and `html_table()` so that the two can
    accept identical set of input shapes:

    - `data`: a 2D list/tuple of rows, a 2D numpy array, or a list of
      dicts (in which case `headers` is derived from the first dict's
      keys unless `headers` is explicitly given).
    - `headers`: a list/tuple/1D numpy array of column names. Optional
      only when `data` is a list of dicts.

    Returns a `(headers, rows)` tuple, both already coerced to native
    (JSON/HTML-safe) types via `_table_cell_to_native`.
    """
    if isinstance(data, np.ndarray):
        assert (
            data.ndim == 2
        ), "`data` as a numpy array must be 2-dimensional (rows x columns)"
        data = data.tolist()
    elif data is not None and not isinstance(data, (list, tuple)):
        raise AssertionError(
            "`data` must be a list, tuple, or numpy array (got %s)"
            % type(data).__name__
        )

    if isinstance(headers, np.ndarray):
        assert headers.ndim == 1, "`headers` as a numpy array must be 1-dimensional"
        headers = headers.tolist()
    elif headers is not None and not isinstance(headers, (list, tuple)):
        raise AssertionError(
            "`headers` must be a list, tuple, or numpy array (got %s)"
            % type(headers).__name__
        )

    has_data = data is not None and len(data) > 0
    has_headers = headers is not None and len(headers) > 0

    if not has_data and not has_headers:
        raise AssertionError("either `data` or `headers` must be provided")

    if has_headers:
        assert isinstance(headers, (list, tuple)), (
            "headers should be a list (got %s)" % type(headers).__name__
        )

    if has_data and isinstance(data[0], dict):
        assert all(
            isinstance(row, dict) for row in data
        ), "all rows in `data` must be dicts if the first row is a dict"
        headers = list(headers) if has_headers else list(data[0].keys())
        rows = [[row.get(h, "") for h in headers] for row in data]
    else:
        assert has_headers, "headers required when data rows are lists/tuples"
        if has_data:
            assert all(
                isinstance(row, (list, tuple)) for row in data
            ), "each row in `data` should be a list or tuple"
        headers = list(headers)
        rows = [list(r) for r in data] if has_data else []

    assert all(
        len(r) == len(headers) for r in rows
    ), "each row must have the same number of columns as headers"

    rows = [[_table_cell_to_native(cell) for cell in row] for row in rows]
    headers = [_table_cell_to_native(h) for h in headers]

    return headers, rows


def _sanitize_nan_key(key):
    """Replace a non-finite float dict key with the token json wrote for it.

    A non-finite *value* becomes None, but a key cannot: JSON keys are
    strings, so the encoder stringifies the float itself. Under the
    ``allow_nan=True`` default that this module encoded with historically,
    that gave "NaN", "Infinity" and "-Infinity"; keep emitting those rather
    than dropping the key or renaming it to "None".
    """
    value = key.item() if isinstance(key, np.generic) else key
    if not isinstance(value, float) or not (math.isnan(value) or math.isinf(value)):
        return key
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"


def _sanitize_nans(obj):
    """Recursively replace NaN/Inf floats with None in nested structures.

    Also coerces numpy scalars (e.g. np.int64, np.bool_) to native Python
    types first: unlike np.floating, they aren't json-serializable on
    their own, so a value like X.min() on an integer array would
    otherwise reach json.dumps() unconverted and raise.
    """
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, (float, np.floating)) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {_sanitize_nan_key(k): _sanitize_nans(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_nans(v) for v in obj]
    return obj


# The message json raises for a NaN or an Inf under allow_nan=False. The C and
# the pure-Python encoders word it identically up to a trailing ": <repr>".
_NON_FINITE_FLOAT_ERROR = "Out of range float values are not JSON compliant"


def _is_non_finite_float_error(error):
    """Whether ``error`` is json reporting a non-finite float, and not something else.

    ``JSONEncoder`` also raises ``ValueError`` for a circular reference, and a
    circular payload handed to ``_sanitize_nans`` recurses until the
    interpreter gives up -- turning a clear "Circular reference detected" into
    a ``RecursionError``. Only the non-finite report is worth a retry.
    """
    return str(error).startswith(_NON_FINITE_FLOAT_ERROR)


def _is_missing_value(value):
    """Whether a plotted coordinate carries no value.

    Clients mark gaps in a series with None, NaN or Inf. Only numbers can be
    NaN or Inf: a categorical axis carries strings, and passing one to
    ``math.isnan`` raises ``TypeError``, so anything non-numeric is present by
    definition.
    """
    if value is None:
        return True
    if isinstance(value, numbers.Real):
        return math.isnan(value) or math.isinf(value)
    return False


class NanSafeEncoder(json.JSONEncoder):
    """JSON encoder that converts NaN and Inf float values to None.

    Standard JSON does not support NaN/Inf. This encoder handles them
    automatically so callers don't need manual nan2none() preprocessing.

    ``_sanitize_nans`` rebuilds the whole payload in pure Python, so it runs
    only once the C encoder has proven it is needed. ``allow_nan=False`` is
    what makes that proof free: it turns a non-finite float into a
    ``ValueError`` raised at the first offending value instead of a ``NaN``
    token buried somewhere in the output. A clean payload therefore pays
    nothing for the check, and -- unlike searching the encoded output for the
    token -- a *string* containing "NaN" cannot trigger the slow path, because
    only a real non-finite float can raise.

    ``encode()`` is deliberately not overridden. ``JSONEncoder.encode`` calls
    ``self.iterencode`` internally, so overriding both sanitized every payload
    twice before the C encoder ever saw it.

    Recovering from that ``ValueError`` means re-encoding from the start, which
    is free on the ``json.dumps`` path and wrong on the other two, so the fast
    path is taken only when both of these hold:

    * ``_one_shot`` is set -- that is, ``json.dumps``, which joins the chunks
      into a single string on return regardless. ``json.dump`` streams instead,
      and restarting there would mean either buffering the whole payload, which
      costs the bounded memory that is the point of streaming, or resuming
      after the caller had already written part of the output.
    * no caller-supplied ``default()`` hook is in play, since a restart would
      hand every object the first attempt reached to the hook a second time.

    Both excluded cases sanitize up front instead: one pass, same output, and
    ``json.dump`` keeps streaming lazily.
    """

    def __init__(self, **kwargs):
        kwargs["allow_nan"] = False
        super().__init__(**kwargs)

    def _has_custom_default(self):
        """Whether ``default()`` is json's own, or a hook someone supplied.

        A subclass overrides the method; ``json.dumps(default=...)`` lands on
        the instance instead, so both spellings have to be checked.
        """
        subclassed = type(self).default is not json.JSONEncoder.default
        return subclassed or "default" in vars(self)

    def iterencode(self, o, _one_shot=False):
        if not _one_shot or self._has_custom_default():
            return json.JSONEncoder.iterencode(
                self, _sanitize_nans(o), _one_shot=_one_shot
            )
        try:
            # Materialized so a non-finite value raises here, where the retry
            # can still start from the beginning. json.dumps is about to join
            # these chunks anyway, so this holds nothing new.
            return iter(list(json.JSONEncoder.iterencode(self, o, _one_shot=True)))
        except ValueError as error:
            if not _is_non_finite_float_error(error):
                raise
        except TypeError:
            # A numpy scalar: json cannot serialize one, but _sanitize_nans
            # coerces it via .item(). With no custom default() hook in play,
            # every TypeError arriving here is json's own.
            pass
        return json.JSONEncoder.iterencode(self, _sanitize_nans(o), _one_shot=True)
