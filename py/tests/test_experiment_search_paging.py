"""Tests for the paged, bounded form of experiment search.

``search()`` answers "which runs match?" and returns all of them; a request
handler cannot, because the answer grows with the store. ``search_page()`` is
the same scan with a page taken out of it and the unpaged total counted
alongside, and it retains only what the page could reach.

The contract worth pinning is that bounding changes cost and nothing else: a
page must equal the same slice of the unbounded result, for every offset, in
both directions, and across the boundary where sorted runs give way to the runs
that have no value to sort by.

A run whose sort value diverged to NaN is one of those value-less runs, and the
reason bounding makes it worth testing: NaN compares ``False`` against every
other value, so ranking it alongside real numbers is not an ordering at all, and
the heap the page is selected through answers by dropping runs that belong on
it.
"""

import math
import shutil
import tempfile
import unittest

from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore
from visdom.experiments.store import _MIN_TRIM_AT, _is_absent, _order_key


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


class TestNonFiniteSortValues(PagingCase):
    """A NaN or Inf metric is no value to sort by, and takes no run down with it.

    NaN only reaches the ranking from a *live* environment: written out and read
    back it is ``null``, since JSON cannot spell a non-finite number. So these
    seed through an env provider, the way the server holds envs while a run is
    logging into them.
    """

    def setUp(self):
        super().setUp()
        self.live = {}
        self.store = ExperimentStore(JSONStore(self._tmp_dir), self.live.get)

    def seed_live(self, count, diverged=(), value=float("nan")):
        """Seed ``count`` runs scoring 0..count-1, with ``diverged`` indices at ``value``."""
        for i in range(count):
            eid = "run-%03d" % i
            self.live[eid] = {"jsons": {}, "reload": {}}
            self.store.log_experiment(eid, params={"lr": 0.001 * i})
            self.store.log_metric(eid, "acc", value if i in diverged else float(i))

    def test_a_nan_run_keeps_its_metric(self):
        """The premise: the value really is NaN here, not the null disk holds."""
        self.seed_live(3, diverged={1})
        metric = self.store.get_experiment("run-001").latest_metric("acc")
        self.assertTrue(math.isnan(metric.value))

    def test_a_nan_does_not_drop_other_runs_from_the_page(self):
        """The reported bug: one diverged run, and good runs vanish from a page."""
        self.seed_live(_MIN_TRIM_AT * 3, diverged={7})
        full = self.store.search(sort_by="acc")
        for descending in (True, False):
            ranked = self.store.search(sort_by="acc", descending=descending)
            for limit in (5, 10, 20):
                page, total = self.store.search_page(
                    sort_by="acc", descending=descending, limit=limit
                )
                self.assertEqual(ids(page), ids(ranked[:limit]))
                self.assertEqual(total, _MIN_TRIM_AT * 3)
        self.assertEqual(len(full), _MIN_TRIM_AT * 3)

    def test_no_run_is_lost_across_a_full_paged_walk(self):
        """Every match is reachable by paging through, NaNs scattered or not."""
        count = _MIN_TRIM_AT * 3
        self.seed_live(count, diverged=set(range(0, count, 9)))
        for descending in (True, False):
            seen = []
            offset = 0
            while True:
                page, total = self.store.search_page(
                    sort_by="acc", descending=descending, offset=offset, limit=10
                )
                if not page:
                    break
                seen.extend(ids(page))
                offset += 10
            self.assertEqual(total, count)
            self.assertEqual(sorted(seen), ["run-%03d" % i for i in range(count)])

    def test_nan_runs_sort_last_in_both_directions(self):
        self.seed_live(4, diverged={1, 2})
        for descending, ordered in (
            (True, ["run-003", "run-000"]),
            (False, ["run-000", "run-003"]),
        ):
            page, _ = self.store.search_page(
                sort_by="acc", descending=descending, limit=10
            )
            self.assertEqual(ids(page)[:2], ordered)
            self.assertEqual(sorted(ids(page)[2:]), ["run-001", "run-002"])

    def test_infinity_sorts_last_too(self):
        """Inf orders fine in Python but persists as null, so it counts as absent."""
        self.seed_live(4, diverged={2}, value=float("inf"))
        page, _ = self.store.search_page(sort_by="acc", limit=10)
        self.assertEqual(ids(page), ["run-003", "run-001", "run-000", "run-002"])

    def test_a_live_nan_ranks_where_the_persisted_null_does(self):
        """A run's position cannot depend on whether its env is still in memory."""
        self.seed_live(6, diverged={4})
        live_order = ids(self.store.search(sort_by="acc"))
        reloaded = ExperimentStore(JSONStore(self._tmp_dir))
        self.assertIsNone(reloaded.get_experiment("run-004").latest_metric("acc").value)
        self.assertEqual(ids(reloaded.search(sort_by="acc")), live_order)

    def test_a_query_still_filters_the_nan_run_out(self):
        """Unchanged: NaN satisfies no ordering comparison, so it never matches."""
        self.seed_live(4, diverged={1})
        page, total = self.store.search_page(query="acc >= 0", sort_by="acc", limit=10)
        self.assertEqual(ids(page), ["run-003", "run-002", "run-000"])
        self.assertEqual(total, 3)


class TestOrderingHelpers(unittest.TestCase):
    """The two guarantees that keep a non-finite value out of the ranking."""

    def test_absent_covers_missing_none_and_non_finite(self):
        for value in (None, float("nan"), float("inf"), float("-inf")):
            self.assertTrue(_is_absent(value), value)
        for value in (0, 0.0, -1.5, False, True, "", "nan", [], 10**400):
            self.assertFalse(_is_absent(value), value)

    def test_order_key_survives_an_int_wider_than_a_float(self):
        """JSON caps no integer, so ordering one must not raise out of a request."""
        self.assertEqual(_order_key(10**400), (1, 0.0, str(10**400)))
        self.assertFalse(_is_absent(10**400))

    def test_order_key_stays_comparable_for_a_non_finite_value(self):
        """Whatever reaches the comparator, the key it returns can be compared."""
        keys = [_order_key(v) for v in (float("nan"), float("inf"), 1.0, "x", True)]
        self.assertEqual(sorted(keys), sorted(reversed(keys)))
        self.assertNotEqual(_order_key(float("nan"))[0], _order_key(1.0)[0])


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
