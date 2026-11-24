#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the t-SNE helpers and backend selection.

``do_tsne`` picks its backend on first call -- openTSNE, then the bundled
bhtsne, then an error naming both -- and keeps the choice in
``visdom._tsne_backend``. Importing visdom must not run that search, because
openTSNE drags scikit-learn and SciPy in behind it; the guard for that is
``test_importing_visdom_does_not_pull_in_a_backend``, which has to measure a
clean interpreter and so runs in a subprocess.

The ladder itself is still exercised by reloading the module with the
candidate backends faked out: a reload resets the cached choice, and it also
covers the import machinery the fakes stand in for. That mutates global state
for the rest of the session, so every reload goes through ``reloaded_visdom``,
which restores the real module even when the test fails.
"""

import importlib
import os
import subprocess
import sys
import textwrap
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

import visdom
from visdom import _get_perplexity, _normalize_tsne

pytestmark = pytest.mark.unit

_MISSING = object()


@pytest.fixture
def reloaded_visdom():
    """Reload ``visdom`` with a patched ``sys.modules``, then put it back.

    Yields a callable taking the ``sys.modules`` overrides to apply; it returns
    the freshly reloaded module. The teardown reload runs unconditionally, so a
    failing assertion cannot leave the rest of the suite running against a
    mocked backend.
    """
    saved = {}

    def reload_with(overrides):
        for name, module in overrides.items():
            saved[name] = sys.modules.get(name, _MISSING)
            sys.modules[name] = module
        return importlib.reload(visdom)

    try:
        yield reload_with
    finally:
        for name, module in saved.items():
            if module is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        importlib.reload(visdom)


def _fake_opentsne(embedding):
    """An ``openTSNE`` stand-in whose ``TSNE(...).fit(X)`` returns ``embedding``."""
    instance = MagicMock()
    instance.fit.return_value = np.asarray(embedding)
    module = types.ModuleType("openTSNE")
    module.TSNE = MagicMock(return_value=instance)
    return module


def _fake_bhtsne(embedding):
    """A ``visdom.extra_deps.bhtsne.bhtsne`` stand-in for ``run_bh_tsne``.

    Returns the ``sys.modules`` overrides plus the leaf module, so a test can
    assert on the call. Every level of the dotted path needs an entry: the
    import machinery stops descending as soon as a name resolves from
    ``sys.modules``, so a gap in the chain leaves the parent package without the
    attribute the ``import ... as`` binding then looks for.
    """
    leaf = types.ModuleType("visdom.extra_deps.bhtsne.bhtsne")
    leaf.run_bh_tsne = MagicMock(return_value=np.asarray(embedding))
    package = types.ModuleType("visdom.extra_deps.bhtsne")
    package.bhtsne = leaf
    extra_deps = types.ModuleType("visdom.extra_deps")
    extra_deps.bhtsne = package
    overrides = {
        "openTSNE": None,
        "visdom.extra_deps": extra_deps,
        "visdom.extra_deps.bhtsne": package,
        "visdom.extra_deps.bhtsne.bhtsne": leaf,
    }
    return overrides, leaf


SQUARE = [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]


# -- _get_perplexity ---------------------------------------------------------


@pytest.mark.parametrize(
    "num_entities,expected",
    [
        (500, 50),  # large: capped at the base of 50
        (200, 50),
        (150, 49),  # the (n - 1) // 3 clamp bites just below 151
        (90, 29),
        (60, 19),
        (21, 6),
        (20, 6),  # below 21 the base is 7, but the clamp still wins
        (10, 3),
        (5, 1),
        (1, 1),  # never drops below 1, however small the input
        (0, 1),
    ],
)
def test_perplexity_table(num_entities, expected):
    """Perplexity follows the size bands, then the (n - 1) // 3 clamp."""
    assert _get_perplexity(num_entities) == expected


@pytest.mark.parametrize("num_entities", [0, 1, 2, 7, 25, 100, 1000])
def test_perplexity_stays_usable(num_entities):
    """Perplexity is always at least 1 and never exceeds (n - 1) // 3."""
    perplexity = _get_perplexity(num_entities)
    assert perplexity >= 1
    assert perplexity <= max(1, (num_entities - 1) // 3)


# -- _normalize_tsne ---------------------------------------------------------


def test_normalize_maps_extremes_to_the_unit_box():
    """The min point lands on (-1, -1) and the max on (1, 1)."""
    result = _normalize_tsne(np.array(SQUARE))
    assert len(result) == 3
    assert result[0] == pytest.approx((-1.0, -1.0))
    assert result[2] == pytest.approx((1.0, 1.0))


def test_normalize_bounds_both_axes():
    """Both axes span exactly [-1, 1] regardless of the input scale."""
    xs, ys = zip(*_normalize_tsne(np.random.rand(50, 2) * 100))
    assert min(xs) == pytest.approx(-1.0)
    assert max(xs) == pytest.approx(1.0)
    assert min(ys) == pytest.approx(-1.0)
    assert max(ys) == pytest.approx(1.0)


def test_normalize_handles_a_degenerate_axis():
    """A zero-range axis collapses to 0, not to a division-by-zero NaN."""
    result = _normalize_tsne(np.array([[5.0, 0.0], [5.0, 1.0], [5.0, 2.0]]))
    xs, ys = zip(*result)
    assert xs == pytest.approx((0.0, 0.0, 0.0))
    assert ys == pytest.approx((-1.0, 0.0, 1.0))


def test_normalize_accepts_a_plain_list():
    """A nested list is coerced, so callers need not pass an ndarray."""
    assert _normalize_tsne(SQUARE)[0] == pytest.approx((-1.0, -1.0))


# -- backend selection -------------------------------------------------------


def test_opentsne_is_preferred(reloaded_visdom):
    """With openTSNE importable it is used, and it drives the perplexity."""
    fake = _fake_opentsne(SQUARE)
    module = reloaded_visdom({"openTSNE": fake})

    result = module.do_tsne(np.random.rand(30, 10).astype(np.float32))

    fake.TSNE.assert_called_once()
    assert fake.TSNE.call_args.kwargs["n_components"] == 2
    assert fake.TSNE.call_args.kwargs["perplexity"] == _get_perplexity(30)
    fake.TSNE.return_value.fit.assert_called_once()
    assert result[0] == pytest.approx((-1.0, -1.0))


def test_falls_back_to_bhtsne(reloaded_visdom):
    """With openTSNE missing, bhtsne is used and receives the input dimensions."""
    overrides, leaf = _fake_bhtsne(SQUARE)
    module = reloaded_visdom(overrides)

    X = np.random.rand(30, 10).astype(np.float32)
    result = module.do_tsne(X)

    leaf.run_bh_tsne.assert_called_once()
    assert leaf.run_bh_tsne.call_args.kwargs["initial_dims"] == 10
    assert leaf.run_bh_tsne.call_args.kwargs["perplexity"] == _get_perplexity(30)
    assert result[2] == pytest.approx((1.0, 1.0))


def test_error_names_both_backends(reloaded_visdom):
    """With neither backend importable, the error points at both of them."""
    module = reloaded_visdom(
        {
            "openTSNE": None,
            "visdom.extra_deps": None,
            "visdom.extra_deps.bhtsne": None,
            "visdom.extra_deps.bhtsne.bhtsne": None,
        }
    )

    with pytest.raises(Exception) as excinfo:
        module.do_tsne(np.random.rand(10, 5))

    message = str(excinfo.value)
    assert "openTSNE" in message
    assert "bhtsne" in message


def test_the_backend_is_resolved_once(reloaded_visdom):
    """The search runs on the first call and the choice is kept.

    ``embeddings()`` calls ``do_tsne`` once per selection, so re-running the
    import ladder each time would put an import attempt on every call.
    """
    fake = _fake_opentsne(SQUARE)
    module = reloaded_visdom({"openTSNE": fake})
    assert module._tsne_backend is None

    X = np.random.rand(30, 10).astype(np.float32)
    module.do_tsne(X)
    chosen = module._tsne_backend
    assert chosen is not None

    module.do_tsne(X)
    assert module._tsne_backend is chosen


def test_a_missing_backend_is_remembered_as_the_error(reloaded_visdom):
    """The negative result is cached too, so it stays one lookup."""
    module = reloaded_visdom(
        {
            "openTSNE": None,
            "visdom.extra_deps": None,
            "visdom.extra_deps.bhtsne": None,
            "visdom.extra_deps.bhtsne.bhtsne": None,
        }
    )

    for _ in range(2):
        with pytest.raises(Exception, match="openTSNE"):
            module.do_tsne(np.random.rand(10, 5))
    assert module._tsne_backend is not None


def test_importing_visdom_does_not_pull_in_a_backend():
    """``import visdom`` must leave torch and the t-SNE stack alone.

    This is the whole point of resolving late: openTSNE pulls scikit-learn and
    SciPy with it, and torch was imported only to build an isinstance tuple.
    Together they were the bulk of a ~3 s import paid by every script that
    imports visdom, including every ``visdom.server`` start.

    It runs in a subprocess because by the time this test executes the suite
    has long since imported both; only a fresh interpreter can answer.
    """
    probe = textwrap.dedent(
        """
        import sys
        import visdom
        leaked = [
            name
            for name in ("torch", "openTSNE", "sklearn", "scipy")
            if name in sys.modules
        ]
        print(",".join(leaked))
        """
    )
    # the child has to import the visdom this test is running against, not
    # whatever an editable install in the environment happens to point at.
    env = dict(os.environ)
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(visdom.__file__)))
    env["PYTHONPATH"] = os.pathsep.join(
        [package_root] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "", "import visdom pulled in " + done.stdout.strip()
