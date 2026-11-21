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


def lock_out(throttle, key, attempts=5):
    """Fail ``attempts`` times in a row, returning the last answer."""
    delay = 0.0
    for _ in range(attempts):
        delay = throttle.record_failure(key)
    return delay


def test_a_fresh_client_may_try():
    assert LoginThrottle().retry_after("10.0.0.1") is None


def test_failures_below_the_threshold_do_not_lock():
    throttle = LoginThrottle(max_failures=5, clock=Clock())

    for _ in range(4):
        assert throttle.record_failure("10.0.0.1") == 0.0

    assert throttle.retry_after("10.0.0.1") is None


def test_the_threshold_failure_locks_for_the_base_delay():
    clock = Clock()
    throttle = LoginThrottle(max_failures=5, base_delay=30.0, clock=clock)

    assert lock_out(throttle, "10.0.0.1") == 30.0
    assert throttle.retry_after("10.0.0.1") == 30.0

    clock.advance(29.9)
    assert 0 < throttle.retry_after("10.0.0.1") < 0.11

    clock.advance(0.1)
    assert throttle.retry_after("10.0.0.1") is None


def test_each_lockout_doubles_until_the_cap():
    clock = Clock()
    throttle = LoginThrottle(base_delay=30.0, max_delay=60.0, clock=clock)

    assert lock_out(throttle, "10.0.0.1") == 30.0
    clock.advance(30.0)
    assert lock_out(throttle, "10.0.0.1") == 60.0
    clock.advance(60.0)
    # 30 * 2**2 is 120; the cap says 60.
    assert lock_out(throttle, "10.0.0.1") == 60.0


def test_a_login_that_gets_in_forgets_the_client():
    throttle = LoginThrottle(max_failures=5, clock=Clock())

    for _ in range(4):
        throttle.record_failure("10.0.0.1")
    throttle.record_success("10.0.0.1")

    # The count restarted, so four more typos buy no lockout.
    for _ in range(4):
        assert throttle.record_failure("10.0.0.1") == 0.0

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

    # A client already refused gets the standing lockout's remainder, and
    # hammering does not wedge the lock open any longer.
    assert throttle.record_failure("10.0.0.1") == 20.0

    clock.advance(20.1)
    assert throttle.retry_after("10.0.0.1") is None


def test_a_client_that_goes_quiet_is_forgotten():
    clock = Clock()
    throttle = LoginThrottle(max_failures=5, max_delay=10.0, clock=clock)

    for _ in range(4):
        throttle.record_failure("10.0.0.1")
    clock.advance(10.0)

    # The abandoned counter was pruned, so the next burst starts fresh.
    for _ in range(4):
        assert throttle.record_failure("10.0.0.1") == 0.0

    assert throttle.retry_after("10.0.0.1") is None
