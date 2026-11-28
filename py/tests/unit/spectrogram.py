#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for ``vis.spectrogram``."""

import numpy as np
import pytest
from scipy import signal

pytestmark = pytest.mark.unit

RATE = 16000


def tone(freq, seconds=1.0, rate=RATE):
    t = np.arange(int(seconds * rate)) / rate
    return np.sin(2 * np.pi * freq * t)


def sent(capture_send, waveform, **opts):
    payload = capture_send(lambda v: v.spectrogram(waveform, opts=opts))["payload"]
    (trace,) = payload["data"]
    return payload, trace


def z_of(trace):
    return np.array(trace["z"])


def peak_freq(trace, column=None):
    z = z_of(trace)
    rows = z.argmax(axis=0) if column is None else [z[:, column].argmax()]
    return np.array(trace["y"])[rows]


def test_a_tone_peaks_at_its_frequency(capture_send):
    _, trace = sent(capture_send, tone(1000), sample_frequency=RATE)
    bin_width = RATE / 1024
    assert np.all(np.abs(peak_freq(trace)[2:-2] - 1000) <= bin_width)


def test_axes_are_seconds_and_hz(capture_send):
    payload, trace = sent(capture_send, tone(440, 2.0), sample_frequency=RATE)
    freqs, times, z = np.array(trace["y"]), np.array(trace["x"]), z_of(trace)
    assert z.shape == (len(freqs), len(times))
    assert freqs[0] == 0 and freqs[-1] == RATE / 2 and len(freqs) == 1024 // 2 + 1
    assert times[0] == 0 and np.all(np.diff(times) > 0)
    assert times[-1] == pytest.approx(2.0, abs=1024 / RATE)
    layout = payload["layout"]
    assert layout["xaxis"]["title"] == {"text": "Time (s)"}
    assert layout["yaxis"]["title"] == {"text": "Frequency (Hz)"}
    assert trace["type"] == "heatmap" and trace["colorscale"] == "Viridis"
    assert trace["colorbar"] == {"title": {"text": "dB"}}


def test_values_are_scipys_stft_in_db(capture_send):
    waveform = np.random.default_rng(0).normal(size=RATE // 2)
    _, trace = sent(capture_send, waveform, sample_frequency=RATE, top_db=500)
    _, _, stft = signal.stft(
        waveform, fs=RATE, window="hann", nperseg=1024, noverlap=768
    )
    expected = 20 * np.log10(np.maximum(np.abs(stft), 1e-10))
    np.testing.assert_allclose(z_of(trace), expected, atol=0.051)


def test_a_rising_chirp_peaks_higher_later(capture_send):
    t = np.arange(2 * RATE) / RATE
    chirp = np.sin(2 * np.pi * (200 + 1500 * t) * t)
    _, trace = sent(capture_send, chirp, sample_frequency=RATE)
    peaks = peak_freq(trace)[4:-4]
    assert np.all(np.diff(peaks) >= -RATE / 1024)
    assert peaks[-1] - peaks[0] > 4000


@pytest.mark.parametrize(
    "shape",
    ["N", "Nx2", "2xN", "1xN", "Nx1"],
)
def test_it_takes_the_waveforms_audio_takes(capture_send, shape):
    left, right = tone(500), tone(2000)
    mono = (left + right) / 2
    waveform = {
        "N": mono,
        "Nx2": np.stack([left, right], axis=1),
        "2xN": np.stack([left, right]),
        "1xN": mono[None, :],
        "Nx1": mono[:, None],
    }[shape]
    _, trace = sent(capture_send, waveform, sample_frequency=RATE)
    _, reference = sent(capture_send, mono, sample_frequency=RATE)
    assert trace["z"] == reference["z"]


def test_a_torch_tensor_is_taken(capture_send):
    torch = pytest.importorskip("torch")
    waveform = tone(800)
    _, from_torch = sent(capture_send, torch.tensor(waveform), sample_frequency=RATE)
    _, from_numpy = sent(capture_send, waveform, sample_frequency=RATE)
    assert from_torch["z"] == from_numpy["z"]


def test_integer_samples_are_taken(capture_send):
    pcm = (tone(1000) * 32767).astype(np.int16)
    _, trace = sent(capture_send, pcm, sample_frequency=RATE)
    assert np.all(np.abs(peak_freq(trace)[2:-2] - 1000) <= RATE / 1024)


def test_a_clip_shorter_than_a_frame_still_has_every_frequency(capture_send):
    _, trace = sent(capture_send, tone(1000, 0.01), sample_frequency=RATE)
    assert len(trace["y"]) == 1024 // 2 + 1
    assert z_of(trace).shape[1] >= 1


def test_one_sample_is_enough(capture_send):
    _, trace = sent(capture_send, np.array([0.5]), sample_frequency=RATE)
    assert np.all(np.isfinite(z_of(trace)))


def test_silence_draws_a_flat_floor(capture_send):
    _, trace = sent(capture_send, np.zeros(RATE), sample_frequency=RATE)
    z = z_of(trace)
    assert np.all(np.isfinite(z)) and z.min() == z.max()


def test_top_db_sets_the_floor_below_the_peak(capture_send):
    waveform = tone(1000) + 1e-6 * np.random.default_rng(1).normal(size=RATE)
    _, trace = sent(capture_send, waveform, sample_frequency=RATE, top_db=40)
    z = z_of(trace)
    assert z.max() - z.min() == pytest.approx(40, abs=0.1)


def test_linear_scale_sends_the_magnitude(capture_send):
    waveform = tone(1000)
    _, trace = sent(capture_send, waveform, sample_frequency=RATE, scale="linear")
    _, _, stft = signal.stft(
        waveform, fs=RATE, window="hann", nperseg=1024, noverlap=768
    )
    np.testing.assert_allclose(z_of(trace), np.abs(stft), rtol=1e-9, atol=1e-12)
    assert trace["colorbar"] == {"title": {"text": "magnitude"}}


def test_fmax_drops_the_rows_above_it(capture_send):
    _, trace = sent(capture_send, tone(1000), sample_frequency=RATE, fmax=2000)
    freqs = np.array(trace["y"])
    assert freqs.max() <= 2000 and freqs.max() > 2000 - RATE / 1024
    assert z_of(trace).shape[0] == len(freqs)


def test_fmax_below_the_first_bin_keeps_0_hz(capture_send):
    _, trace = sent(capture_send, tone(1000), sample_frequency=RATE, fmax=1)
    assert trace["y"] == [0.0]


def test_n_fft_and_hop_length_set_the_bins_and_frames(capture_send):
    _, trace = sent(
        capture_send, tone(1000), sample_frequency=RATE, n_fft=256, hop_length=256
    )
    assert len(trace["y"]) == 129
    assert np.diff(trace["x"])[0] == pytest.approx(256 / RATE)


def test_a_long_clip_is_capped_and_keeps_a_short_click(capture_send):
    waveform = 0.01 * tone(300, 60.0)
    waveform[30 * RATE : 30 * RATE + 40] = 1.0  # a 2.5 ms click at 30 s
    _, trace = sent(capture_send, waveform, sample_frequency=RATE, max_columns=200)
    z, times = z_of(trace), np.array(trace["x"])
    assert z.shape[1] <= 200 and len(times) == z.shape[1]
    loudest = z[300, :]  # ~4.7 kHz, above the tone
    assert times[loudest.argmax()] == pytest.approx(30, abs=0.5)
    assert np.all(np.diff(times) > 0) and times[-1] == pytest.approx(60, abs=0.5)


@pytest.mark.parametrize(
    "length, n_fft, hop, max_columns",
    [
        (5000, 256, 64, 7),
        (5001, 255, 17, 50),
        (300, 512, 512, 1),
        (1, 8, 3, 2),
        (70000, 64, 1, 333),
        (9999, 2, 1, 1000),
    ],
)
def test_capped_columns_are_scipys_frames_pooled(length, n_fft, hop, max_columns):
    from visdom import _stft_magnitude

    waveform = np.random.default_rng(length).normal(size=length)
    padded = np.pad(waveform, (0, max(0, n_fft - length)))
    _, times, stft = signal.stft(
        padded, window="hann", nperseg=n_fft, noverlap=n_fft - hop
    )
    group = -(-stft.shape[1] // max_columns)
    starts = np.arange(0, stft.shape[1], group)
    expected = np.maximum.reduceat(np.abs(stft), starts, axis=1)
    z, frames = _stft_magnitude(padded, n_fft, hop, max_columns)
    np.testing.assert_allclose(z, expected, rtol=1e-9, atol=1e-12)
    expected_times = np.add.reduceat(times, starts) / np.diff(
        np.append(starts, len(times))
    )
    np.testing.assert_allclose(frames * hop, expected_times)


def test_a_long_clip_does_not_hold_its_whole_stft():
    import tracemalloc

    from visdom import _stft_magnitude

    waveform = np.random.default_rng(2).normal(size=600 * 44100)
    tracemalloc.start()
    z, _ = _stft_magnitude(waveform, 1024, 256, 1000)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert z.shape[0] == 513 and 900 < z.shape[1] <= 1000
    assert peak < waveform.nbytes + 100 * 2**20


def test_the_default_cap_keeps_a_long_clip_small(capture_send):
    _, trace = sent(capture_send, tone(440, 120.0), sample_frequency=RATE)
    assert len(trace["x"]) <= 1000


def test_the_callers_opts_are_left_alone(capture_send):
    opts = {"sample_frequency": RATE}
    capture_send(lambda v: v.spectrogram(tone(440), opts=opts))
    assert opts == {"sample_frequency": RATE}


def test_title_and_colormap_are_passed_on(capture_send):
    payload, trace = sent(
        capture_send, tone(440), sample_frequency=RATE, title="Clip", colormap="Hot"
    )
    assert payload["layout"]["title"] == {"text": "Clip"}
    assert trace["colorscale"] == "Hot"


@pytest.mark.parametrize(
    "waveform, message",
    [
        (np.array([]), "empty"),
        (np.array([0.0, np.nan]), "finite"),
        (np.array([0.0, np.inf]), "finite"),
        (np.array([1 + 1j, 0]), "complex"),
        (np.array(["a", "b"]), "numbers"),
        (np.zeros((2, 3, 4)), "1D vector"),
        (np.zeros((5, 3)), "1D vector"),
        (None, "needs a waveform"),
    ],
    ids=["empty", "nan", "inf", "complex", "strings", "3d", "5x3", "none"],
)
def test_a_bad_waveform_is_refused(offline_client, waveform, message):
    with pytest.raises(ValueError, match=message):
        offline_client.spectrogram(waveform)


@pytest.mark.parametrize(
    "opts, message",
    [
        ({"sample_frequency": 0}, "sample_frequency"),
        ({"sample_frequency": -16000}, "sample_frequency"),
        ({"sample_frequency": float("nan")}, "sample_frequency"),
        ({"sample_frequency": True}, "sample_frequency"),
        ({"sample_frequency": "16000"}, "sample_frequency"),
        ({"n_fft": 1}, "n_fft"),
        ({"n_fft": 512.0}, "n_fft"),
        ({"n_fft": True}, "n_fft"),
        ({"hop_length": 0}, "hop_length"),
        ({"n_fft": 256, "hop_length": 257}, "hop_length"),
        ({"scale": "log"}, "scale"),
        ({"top_db": 0}, "top_db"),
        ({"top_db": float("inf")}, "top_db"),
        ({"fmax": 0}, "fmax"),
        ({"max_columns": 0}, "max_columns"),
    ],
)
def test_a_bad_opt_is_refused(offline_client, opts, message):
    with pytest.raises(ValueError, match=message):
        offline_client.spectrogram(tone(440), opts=opts)


def test_whole_number_and_numpy_opts_are_taken(capture_send):
    _, trace = sent(
        capture_send,
        tone(440),
        sample_frequency=np.float64(16e3),
        n_fft=np.int64(512),
        hop_length=np.int32(128),
    )
    assert len(trace["y"]) == 257
