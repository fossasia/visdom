#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Audio tensors must not leave WAV files in the temporary directory."""

import base64
from io import BytesIO
import re
import tempfile

import numpy as np
import pytest
from scipy.io import wavfile

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("stereo", [False, True])
@pytest.mark.parametrize("silent", [False, True])
def test_tensor_audio_encodes_without_temporary_files(
    capture_send, monkeypatch, tmp_path, stereo, silent
):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    samples = np.array([0.0, -1.0, 0.5, 1.0])
    if silent:
        samples[:] = 0
    if stereo:
        samples = np.column_stack((samples, samples[::-1]))
    original = samples.copy()

    sent = capture_send(
        lambda v: v.audio(tensor=samples, opts={"sample_frequency": 16000})
    )

    markup = sent["payload"]["data"][0]["content"]
    encoded = re.search(r"data:audio/wav;base64,([^\"]+)", markup).group(1)
    rate, decoded = wavfile.read(BytesIO(base64.b64decode(encoded)))
    assert rate == 16000
    np.testing.assert_array_equal(decoded, (samples * 32767).astype(np.int16))
    np.testing.assert_array_equal(samples, original)
    assert list(tmp_path.iterdir()) == []


def test_tensor_audio_does_not_leave_files_when_encoding_fails(
    offline_client, monkeypatch, tmp_path
):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    write = wavfile.write

    def fail_after_write(destination, rate, samples):
        write(destination, rate, samples)
        raise OSError("encoding interrupted")

    monkeypatch.setattr(wavfile, "write", fail_after_write)
    with pytest.raises(OSError, match="encoding interrupted"):
        offline_client.audio(tensor=np.zeros(4))
    assert list(tmp_path.iterdir()) == []


def test_audio_file_is_read_without_changing_or_removing_it(capture_send, tmp_path):
    path = tmp_path / "recording.wav"
    wavfile.write(path, 16000, np.array([0, 100, -100], dtype=np.int16))
    original = path.read_bytes()

    sent = capture_send(lambda v: v.audio(audiofile=str(path)))

    markup = sent["payload"]["data"][0]["content"]
    assert base64.b64encode(original).decode("ascii") in markup
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
