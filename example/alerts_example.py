#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Demo of metric alerts: a rule on a run, and the run that sets it off.

A rule is attached to an environment and evaluated by the server where the
observations arrive, so it is ``log_metrics`` that fires one -- a run that logs
nothing never does. Watch the dashboard while this runs: each firing arrives as
a toast in the browser watching that environment.

Run it against a live server:

    python example/alerts_example.py
    python example/alerts_example.py -run stalled
    python example/alerts_example.py -env run-7 -port 8097

The webhook section needs a server that was started with the two flags that
allow one, and is skipped otherwise:

    python -m visdom.server -allow_webhooks -webhook_hosts hooks.example.com

The training loop here is a few lines of arithmetic rather than a model: what
the demo is about is which observation fires a rule and which one does not.
"""

import argparse
import time

from visdom import Visdom


def threshold(vis, env):
    """A loss that climbs past a threshold, and the debounce in front of it."""
    vis.set_alert("loss", "> 2.0", for_steps=3, env=env)

    # It fires on the third consecutive observation over the line.
    for step, loss in enumerate([0.9, 2.4, 0.8, 2.2, 2.3, 2.6, 2.7], start=1):
        vis.log_metrics({"loss": loss}, step=step, env=env)
        print("step {0}: loss={1}".format(step, loss))
        time.sleep(0.4)

    print("fired:", [rule["fire_count"] for rule in vis.list_alerts(env=env)])


def diverged(vis, env):
    """A loss that stops being a number at all."""
    vis.set_alert("grad", "nan", message="the gradient diverged", env=env)

    for step, grad in enumerate([1.2, 0.8, float("nan")], start=1):
        vis.log_metrics({"grad": grad}, step=step, env=env)
        print("step {0}: grad={1}".format(step, grad))
        time.sleep(0.4)

    # A threshold could not have caught that: every comparison against a NaN
    # is false.


def stalled(vis, env):
    """An accuracy that stops improving."""
    vis.set_alert("accuracy", "stalled", patience=3, goal="max", env=env)

    for step, accuracy in enumerate([0.71, 0.80, 0.79, 0.80, 0.78], start=1):
        vis.log_metrics({"accuracy": accuracy}, step=step, env=env)
        print("step {0}: accuracy={1}".format(step, accuracy))
        time.sleep(0.4)


def webhook(vis, env, url):
    """The same rule, delivered to a url instead of to a browser.

    The server makes the request, so where it may post is the operator's
    decision: without ``-allow_webhooks`` and the host named in
    ``-webhook_hosts`` this is refused with 403 at set time, rather than
    quietly never delivered.
    """
    if not url:
        print("no -webhook_url given, skipping")
        return

    try:
        vis.set_alert("loss", "> 2.0", action="webhook", url=url, env=env)
    except Exception as error:
        print("the server would not take the rule:", error)
        return

    vis.log_metrics({"loss": 2.5}, step=1, env=env)
    print("posted the firing to", url)


def clear(vis, env):
    """Stop watching, and read back what is left."""
    for rule in vis.list_alerts(env=env):
        vis.clear_alert(rule["key"], env=env)
    print("rules left:", vis.list_alerts(env=env))


SECTIONS = {
    "threshold": threshold,
    "diverged": diverged,
    "stalled": stalled,
    "webhook": webhook,
    "clear": clear,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-port", type=int, default=8097)
    parser.add_argument("-server", default="http://localhost")
    parser.add_argument("-env", default="alerts-demo")
    parser.add_argument(
        "-run",
        default="all",
        help="which section to run: " + ", ".join(SECTIONS) + ", or all",
    )
    parser.add_argument(
        "-webhook_url",
        default="",
        help="where the webhook section posts to; needs a server started "
        "with -allow_webhooks and this host in -webhook_hosts",
    )
    args = parser.parse_args()

    vis = Visdom(port=args.port, server=args.server, env=args.env)
    if not vis.check_connection():
        raise SystemExit(
            "no server on {0}:{1} -- start one with python -m visdom.server".format(
                args.server, args.port
            )
        )

    wanted = list(SECTIONS) if args.run == "all" else [args.run]
    for name in wanted:
        if name not in SECTIONS:
            raise SystemExit("unknown section {0!r}".format(name))

    for name in wanted:
        print("\n== {0}".format(name))
        if name == "webhook":
            SECTIONS[name](vis, args.env, args.webhook_url)
        else:
            SECTIONS[name](vis, args.env)


if __name__ == "__main__":
    main()
