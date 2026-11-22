#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The login lockout counter, exercised on a clock the tests move by hand.

``LoginThrottle`` is what stands between an attacker and unlimited guessing
at the single credential a login-enabled server knows: every rejected
attempt is counted per client, and enough of them in a row buys the client
a lockout that doubles each time it reoffends.
"""

import pytest

from visdom.utils.server_utils import LoginThrottle

pytestmark = pytest.mark.unit


class Clock:
    """A monotonic clock that only moves when a test moves it."""

    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def attempt(throttle, key):
    """One login attempt as the handler makes it: reserve, then confirm.

    An attempt that is refused at admission answers with the wait instead
    of a verdict, exactly as ``IndexHandler.post`` answers it with a 429.
    """
    wait = throttle.admit(key)
    return wait if wait is not None else throttle.record_failure(key)


def lock_out(throttle, key, attempts=5):
    """Fail ``attempts`` times in a row, returning the last answer."""
    delay = 0.0
    for _ in range(attempts):
        delay = attempt(throttle, key)
    return delay


def test_a_fresh_client_may_try():
    assert LoginThrottle().retry_after("10.0.0.1") is None


def test_failures_below_the_threshold_do_not_lock():
    throttle = LoginThrottle(max_failures=5, clock=Clock())

    for _ in range(4):
        assert attempt(throttle, "10.0.0.1") == 0.0

    assert throttle.retry_after("10.0.0.1") is None


def test_in_flight_attempts_count_against_the_limit():
    """A burst of concurrent requests cannot all pass the limit check.

    The count is taken at admission, before the derivation is spent, so
    the sixth request of a burst arrives while the first five are still
    in flight and finds the limit already spent on them -- rather than
    waiting for the first ``record_failure`` to land, which a passive
    check would have let past.
    """
    throttle = LoginThrottle(max_failures=5, base_delay=30.0, clock=Clock())

    for _ in range(5):
        assert throttle.admit("10.0.0.1") is None

    # No verdict has landed yet; the limit is already spent.
    assert throttle.admit("10.0.0.1") == 30.0


def test_a_burst_arms_only_when_the_fifth_failure_is_confirmed():
    """Reservations alone do not arm the lockout; confirmed failures do.

    A burst of five spends the limit at admission, but spending the
    limit is not the same as five attempts failing: the lockout waits
    for the fifth verdict to land, so a burst whose attempts were all
    admitted and then abandoned by the client's own side has cost some
    derivations, not a lockout.
    """
    clock = Clock()
    throttle = LoginThrottle(max_failures=5, base_delay=30.0, clock=clock)

    for _ in range(5):
        assert throttle.admit("10.0.0.1") is None
    for _ in range(4):
        assert throttle.record_failure("10.0.0.1") == 0.0

    # Four reservations confirmed: nothing armed yet.
    assert throttle.retry_after("10.0.0.1") is None

    # The fifth confirm arms the lockout, and only that confirm.
    assert throttle.record_failure("10.0.0.1") == 30.0
    assert throttle.retry_after("10.0.0.1") == 30.0


def test_a_success_releases_the_outstanding_reservations():
    throttle = LoginThrottle(max_failures=5, clock=Clock())

    for _ in range(4):
        assert throttle.admit("10.0.0.1") is None
    throttle.record_success("10.0.0.1")

    # The client was forgotten whole, reservations and all.
    assert throttle.admit("10.0.0.1") is None


def test_the_threshold_failure_locks_for_the_base_delay():
    clock = Clock()
    throttle = LoginThrottle(max_failures=5, base_delay=30.0, clock=clock)

    assert lock_out(throttle, "10.0.0.1") == 30.0
    assert throttle.retry_after("10.0.0.1") == 30.0

    clock.advance(29.9)
    assert 0 < throttle.retry_after("10.0.0.1") < 0.11

    clock.advance(0.1)
    assert throttle.retry_after("10.0.0.1") is None


def test_an_attempt_during_a_lockout_is_refused_at_admission():
    clock = Clock()
    throttle = LoginThrottle(max_failures=5, base_delay=30.0, clock=clock)

    lock_out(throttle, "10.0.0.1")
    clock.advance(10.0)

    # The lockout's remainder, with no derivation spent on the attempt.
    assert throttle.admit("10.0.0.1") == 20.0


def test_each_lockout_doubles_until_the_cap():
    clock = Clock()
    throttle = LoginThrottle(base_delay=30.0, max_delay=60.0, clock=clock)

    assert lock_out(throttle, "10.0.0.1") == 30.0
    clock.advance(30.0)
    assert lock_out(throttle, "10.0.0.1") == 60.0
    clock.advance(60.0)
    # 30 * 2**2 is 120; the cap says 60.
    assert lock_out(throttle, "10.0.0.1") == 60.0


def test_reoffending_forever_stays_at_the_cap():
    """The doubling cannot walk its exponent past what a float holds.

    A client that reoffends often enough used to grow the exponent until
    ``30.0 * 2 ** 1024`` overflowed and took the login route down with
    it. The exponent is capped before the power is evaluated now, so
    every answer past the cap is the cap.
    """
    clock = Clock()
    throttle = LoginThrottle(base_delay=1.0, max_delay=900.0, clock=clock)

    # One full lockout per turn -- five confirmed failures, then the wait
    # served -- for four thousand lockouts, walking the exponent far
    # past any value a float holds.
    for _ in range(4000):
        delay = lock_out(throttle, "10.0.0.1")
        assert delay <= 900.0
        clock.advance(delay)

    # The client has reoffended thousands of times, and the very next
    # lockout is the cap exactly.
    assert lock_out(throttle, "10.0.0.1") == 900.0


def test_a_login_that_gets_in_forgets_the_client():
    throttle = LoginThrottle(max_failures=5, clock=Clock())

    for _ in range(4):
        attempt(throttle, "10.0.0.1")
    throttle.record_success("10.0.0.1")

    # The count restarted, so four more typos buy no lockout.
    for _ in range(4):
        assert attempt(throttle, "10.0.0.1") == 0.0

    assert throttle.retry_after("10.0.0.1") is None


def test_clients_are_counted_separately():
    throttle = LoginThrottle(max_failures=5, clock=Clock())

    lock_out(throttle, "10.0.0.1")

    assert throttle.retry_after("10.0.0.2") is None
    assert throttle.record_failure("10.0.0.2") == 0.0


def test_failures_during_a_lockout_extend_nothing():
    clock = Clock()
    throttle = LoginThrottle(max_failures=5, base_delay=30.0, clock=clock)

    lock_out(throttle, "10.0.0.1")
    clock.advance(10.0)

    # A confirm landing while a sibling attempt already armed the
    # lockout gets the standing remainder, and hammering does not wedge
    # the lock open any longer.
    assert throttle.record_failure("10.0.0.1") == 20.0

    clock.advance(20.1)
    assert throttle.retry_after("10.0.0.1") is None


def test_a_client_that_goes_quiet_is_forgotten():
    clock = Clock()
    throttle = LoginThrottle(max_failures=5, max_delay=10.0, clock=clock)

    for _ in range(4):
        attempt(throttle, "10.0.0.1")
    clock.advance(10.0)

    # The abandoned counter was pruned, so the next burst starts fresh.
    for _ in range(4):
        assert attempt(throttle, "10.0.0.1") == 0.0

    assert throttle.retry_after("10.0.0.1") is None
