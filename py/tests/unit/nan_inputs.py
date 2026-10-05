#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests: NaN in user data must not corrupt t-SNE or audio output."""

import warnings

import numpy as np
import pytest

import visdom
from visdom import _normalize_tsne

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("col", [0, 1])
def test_normalize_tsne_nan_does_not_collapse_axis(col):
    """One NaN used to make the range NaN, zeroing the whole axis."""
    Y = np.random.default_rng(0).standard_normal((50, 2))
    Y[3, col] = np.nan

    result = np.asarray(_normalize_tsne(Y))

    finite = result[:, col][~np.isnan(result[:, col])]
    assert finite.min() == pytest.approx(-1.0)
    assert finite.max() == pytest.approx(1.0)


def test_audio_nan_sample_becomes_silence(offline_client, monkeypatch):
    """A NaN sample used to make the scale factor NaN and corrupt the cast."""
    captured = {}

    def fake_write(path, freq, data):
        captured["data"] = np.array(data)

    monkeypatch.setattr("scipy.io.wavfile.write", fake_write)
    monkeypatch.setattr(visdom, "loadfile", lambda *a, **k: b"")
    monkeypatch.setattr(offline_client, "_send", lambda *a, **k: "win")

    tensor = np.random.default_rng(1).standard_normal(1000)
    tensor[42] = np.nan

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        offline_client.audio(tensor=tensor, opts={"sample_frequency": 44100})

    assert captured["data"][42] == 0
    assert np.abs(captured["data"]).max() > 0
