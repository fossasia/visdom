"""
Tests for visdom/__init__.py
"""

import numpy as np
import pytest

from visdom import Visdom

pytestmark = pytest.mark.unit


class TestVisdomEmbeddings:
    """Tests for the Visdom.embeddings() method."""

    def test_embeddings_rejects_non_2d_features(self, monkeypatch):
        """embeddings() should raise ValueError when features is not 2D."""
        monkeypatch.setattr("visdom.do_tsne", lambda x: np.array([[0.0, 0.0]]))
        v = Visdom(
            offline=True,
            use_incoming_socket=False,
            log_to_filename="/tmp/visdom_test.log",
        )
        features = [[1, 2, 3], [4, 5]]  # ragged list
        labels = ["a", "b"]

        with pytest.raises(ValueError, match="features must be a 2D array"):
            v.embeddings(features, labels)

    def test_embeddings_rejects_non_numeric_features(self, monkeypatch):
        """embeddings() should raise ValueError when features is non-numeric 2D array."""
        monkeypatch.setattr("visdom.do_tsne", lambda x: np.array([[0.0, 0.0]]))
        v = Visdom(
            offline=True,
            use_incoming_socket=False,
            log_to_filename="/tmp/visdom_test.log",
        )
        features = [["a", "b"], ["c", "d"]]  # 2D but non-numeric
        labels = ["a", "b"]

        with pytest.raises(ValueError, match="features must be a 2D array"):
            v.embeddings(features, labels)

    def test_embeddings_accepts_valid_2d_features(self, monkeypatch):
        """embeddings() should accept valid 2D numeric features."""
        monkeypatch.setattr(
            "visdom.do_tsne", lambda x: np.array([[0.0, 0.0], [1.0, 1.0]])
        )
        monkeypatch.setattr(Visdom, "_send", lambda self, *a, **k: 1)
        monkeypatch.setattr(Visdom, "_register_embeddings", lambda self, *a, **k: None)
        v = Visdom(
            offline=True,
            use_incoming_socket=False,
            log_to_filename="/tmp/visdom_test.log",
        )
        features = [[1.0, 2.0], [3.0, 4.0]]
        labels = ["a", "b"]

        try:
            v.embeddings(features, labels)
        except ValueError:
            pytest.fail(
                "embeddings() raised ValueError unexpectedly for valid 2D features"
            )
