"""Tests for the paged, bounded form of experiment search.

``search()`` answers "which runs match?" and returns all of them; a request
handler cannot, because the answer grows with the store. ``search_page()`` is
the same scan with a page taken out of it and the unpaged total counted
alongside, and it retains only what the page could reach.

The contract worth pinning is that bounding changes cost and nothing else: a
page must equal the same slice of the unbounded result, for every offset, in
both directions, and across the boundary where sorted runs give way to the runs
that have no value to sort by.
"""

import shutil
import tempfile
import unittest

from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore
from visdom.experiments.store import _MIN_TRIM_AT


def ids(experiments):
    return [experiment.env_id for experiment in experiments]


class PagingCase(unittest.TestCase):
    """A store of runs with distinct, tied and absent sort values."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_paging_")
        self.store = ExperimentStore(JSONStore(self._tmp_dir))

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def seed(self, count, tied=0, without_metric=0):
        """Create ``count`` runs scoring 0..count-1, plus ties and metric-less runs."""
        for i in range(count):
            eid = "run-%03d" % i
            self.store.log_experiment(eid, params={"lr": 0.001 * i})
            self.store.log_metric(eid, "acc", float(i))
        for i in range(tied):
            eid = "tie-%03d" % i
            self.store.log_experiment(eid, params={"lr": 0.5})
            self.store.log_metric(eid, "acc", 100.0)
        for i in range(without_metric):
            eid = "bare-%03d" % i
            self.store.log_experiment(eid, params={"lr": 0.5})


class TestPageMatchesUnboundedSearch(PagingCase):
    """A page is exactly the corresponding slice of the full result."""

    def test_every_offset_agrees_descending(self):
        self.seed(12)
        full = self.store.search(sort_by="acc")
        for offset in range(0, 14, 3):
            end = offset + 4
            page, total = self.store.search_page(sort_by="acc", offset=offset, limit=4)
            self.assertEqual(ids(page), ids(full[offset:end]))
            self.assertEqual(total, 12)

    def test_every_offset_agrees_ascending(self):
        self.seed(12)
        full = self.store.search(sort_by="acc", descending=False)
        for offset in range(0, 14, 3):
            end = offset + 4
            page, _ = self.store.search_page(
                sort_by="acc", descending=False, offset=offset, limit=4
            )
            self.assertEqual(ids(page), ids(full[offset:end]))

    def test_page_respects_the_query(self):
        self.seed(12)
        page, total = self.store.search_page(query="acc >= 8", sort_by="acc", limit=10)
        self.assertEqual(ids(page), ["run-011", "run-010", "run-009", "run-008"])
        self.assertEqual(total, 4)

    def test_total_is_unpaged(self):
        self.seed(12)
        page, total = self.store.search_page(sort_by="acc", limit=3)
        self.assertEqual(len(page), 3)
        self.assertEqual(total, 12)

    def test_limit_zero_counts_without_returning(self):
        self.seed(5)
        page, total = self.store.search_page(sort_by="acc", limit=0)
        self.assertEqual(page, [])
        self.assertEqual(total, 5)

    def test_limit_none_returns_everything(self):
        self.seed(5)
        page, total = self.store.search_page(sort_by="acc", limit=None)
        self.assertEqual(ids(page), ids(self.store.search(sort_by="acc")))
        self.assertEqual(total, 5)

    def test_offset_past_the_end_is_empty(self):
        self.seed(3)
        page, total = self.store.search_page(sort_by="acc", offset=99, limit=5)
        self.assertEqual(page, [])
        self.assertEqual(total, 3)

    def test_negative_paging_is_rejected(self):
        self.seed(1)
        with self.assertRaises(ValueError):
            self.store.search_page(offset=-1)
        with self.assertRaises(ValueError):
            self.store.search_page(limit=-1)


class TestTiesAndMissingValues(PagingCase):
    """Bounding must not disturb tie order or where value-less runs land."""

    def test_ties_keep_scan_order_in_both_directions(self):
        self.seed(2, tied=5)
        for descending in (True, False):
            full = self.store.search(sort_by="acc", descending=descending)
            page, _ = self.store.search_page(
                sort_by="acc", descending=descending, limit=20
            )
            self.assertEqual(ids(page), ids(full))
            tied = [eid for eid in ids(page) if eid.startswith("tie-")]
            self.assertEqual(tied, sorted(tied))

    def test_ties_survive_trimming(self):
        """Enough tied runs to force repeated trims still rank identically."""
        self.seed(0, tied=_MIN_TRIM_AT * 3)
        full = self.store.search(sort_by="acc")
        page, total = self.store.search_page(sort_by="acc", limit=5)
        self.assertEqual(total, _MIN_TRIM_AT * 3)
        self.assertEqual(ids(page), ids(full[:5]))

    def test_runs_without_the_sort_field_come_last(self):
        self.seed(3, without_metric=2)
        page, total = self.store.search_page(sort_by="acc", limit=10)
        self.assertEqual(total, 5)
        self.assertEqual(ids(page)[:3], ["run-002", "run-001", "run-000"])
        self.assertEqual(sorted(ids(page)[3:]), ["bare-000", "bare-001"])

    def test_a_page_straddling_the_missing_boundary(self):
        self.seed(4, without_metric=3)
        full = self.store.search(sort_by="acc")
        page, _ = self.store.search_page(sort_by="acc", offset=2, limit=4)
        self.assertEqual(ids(page), ids(full[2:6]))

    def test_a_page_entirely_inside_the_missing_tail(self):
        self.seed(2, without_metric=3)
        full = self.store.search(sort_by="acc")
        page, _ = self.store.search_page(sort_by="acc", offset=3, limit=2)
        self.assertEqual(ids(page), ids(full[3:5]))

    def test_missing_runs_are_not_reached_by_an_early_page(self):
        self.seed(6, without_metric=2)
        page, total = self.store.search_page(sort_by="acc", limit=2)
        self.assertEqual(ids(page), ["run-005", "run-004"])
        self.assertEqual(total, 8)

    def test_unsorted_paging_keeps_backend_order(self):
        self.seed(6)
        full = self.store.search(sort_by=None)
        page, total = self.store.search_page(sort_by=None, offset=1, limit=3)
        self.assertEqual(ids(page), ids(full[1:4]))
        self.assertEqual(total, 6)


class TestBoundedRetention(PagingCase):
    """The scan holds the page, not the store."""

    def test_scan_retains_only_what_the_page_can_reach(self):
        self.seed(_MIN_TRIM_AT * 4)
        present, missing, total = self.store._scan(None, "acc", descending=True, keep=5)
        self.assertEqual(total, _MIN_TRIM_AT * 4)
        self.assertLessEqual(len(present), max(2 * 5, _MIN_TRIM_AT))
        self.assertEqual(missing, [])

    def test_missing_tail_is_bounded_too(self):
        self.seed(0, without_metric=_MIN_TRIM_AT * 2)
        _, missing, total = self.store._scan(None, "acc", descending=True, keep=3)
        self.assertEqual(total, _MIN_TRIM_AT * 2)
        self.assertEqual(len(missing), 3)

    def test_unbounded_scan_still_retains_everything(self):
        self.seed(10, without_metric=2)
        present, missing, total = self.store._scan(None, "acc", descending=True)
        self.assertEqual(total, 12)
        self.assertEqual(len(present), 10)
        self.assertEqual(len(missing), 2)


if __name__ == "__main__":
    unittest.main()
