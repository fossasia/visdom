#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Demo of the asyncio client, ``visdom.async_client.AsyncVisdom``.

Run it against a live server:

    python example/async_demo.py -run all

Every section here has a synchronous equivalent that would work exactly the
same way; the point of each is what the event loop is free to do meanwhile.
"""

import argparse
import asyncio
import getpass
import ipaddress
import time
from urllib.parse import urlparse

import numpy as np

from visdom.async_client import AsyncVisdom


async def heartbeat(label, interval=0.01):
    """Tick on the event loop, so a stalled loop is visible as a gap.

    Everything below runs with one of these alongside it. A blocking client
    would let it tick once and then not again until the plots were done.
    """
    ticks = 0
    started = time.time()
    try:
        while True:
            await asyncio.sleep(interval)
            ticks += 1
    except asyncio.CancelledError:
        elapsed = time.time() - started
        print("  [{0}] loop ticked {1} times in {2:.2f}s".format(label, ticks, elapsed))
        raise


async def with_heartbeat(label, coro):
    """Run ``coro`` while a heartbeat ticks, and report both."""
    beat = asyncio.ensure_future(heartbeat(label))
    try:
        return await coro
    finally:
        beat.cancel()
        await asyncio.gather(beat, return_exceptions=True)


async def demo_concurrent(vis, env):
    """Four plots at once, from one client.

    ``gather`` is where the concurrency comes from: each call runs its
    synchronous plot body on a worker thread of the client's own pool, and the
    four POSTs are in flight together. Give them distinct windows -- the
    wrapped client is no more thread-safe than the synchronous one.
    """
    print("concurrent: four line plots with gather")
    x = np.linspace(0, 4 * np.pi, 200)

    async def run():
        await asyncio.gather(
            *(
                vis.line(
                    X=x,
                    Y=np.sin(x + phase),
                    win="concurrent_{0}".format(index),
                    env=env,
                    opts=dict(title="phase {0:.2f}".format(phase)),
                )
                for index, phase in enumerate(np.linspace(0, np.pi, 4))
            )
        )

    started = time.time()
    await with_heartbeat("concurrent", run())
    print("  four windows in {0:.2f}s".format(time.time() - started))


async def demo_append(vis, env, frames=100):
    """An append loop -- the path issue #771 profiled.

    ``AsyncVisdom.create`` defaults ``use_preflight_checks`` to ``False``, so
    each frame is a single POST: the server lays the window out from the
    ``layout_create`` the client sends with the first append, instead of the
    client asking ``win_exists`` first. That is one round trip per frame rather
    than two.
    """
    print("append: {0} frames into one window".format(frames))

    async def run():
        for step in range(frames):
            await vis.line(
                X=np.array([step]),
                Y=np.array([np.sin(step / 10.0)]),
                win="append",
                env=env,
                update="append",
                opts=dict(title="append loop"),
            )

    started = time.time()
    await with_heartbeat("append", run())
    elapsed = time.time() - started
    print("  {0:.0f} frames/s serially".format(frames / elapsed))


async def demo_images(vis, env, count=8):
    """Eight images at once, to show where the encoding runs.

    Encoding a PNG and base64-ing it is CPU work, and in the synchronous
    client it happens on whichever thread called ``image``. Here the plot body
    -- encode included -- is already on a worker, so the loop stays free
    without the caller doing anything about it.
    """
    print("images: {0} encodes at once".format(count))

    async def run():
        await asyncio.gather(
            *(
                vis.image(
                    np.random.rand(3, 256, 256),
                    win="image_{0}".format(index),
                    env=env,
                    opts=dict(title="image {0}".format(index)),
                )
                for index in range(count)
            )
        )

    started = time.time()
    await with_heartbeat("images", run())
    print("  {0} images in {1:.2f}s".format(count, time.time() - started))


async def demo_callbacks(vis, env, wait=10):
    """A coroutine event handler on the backchannel.

    Registration is not a coroutine -- it is bookkeeping, and never reaches the
    server. The handler may be a plain function or, as here, a coroutine
    function; a coroutine runs on the client's own loop, so it can await other
    calls on this same client. Needs ``use_incoming_socket=True``, which
    ``create`` leaves off by default.
    """
    if not vis.use_socket:
        print("callbacks: skipped, run with -use_incoming_socket")
        return
    print("callbacks: type in the window, then press enter in the browser")
    win = await vis.text("Type here and press enter.", win="callbacks", env=env)
    seen = asyncio.Event()

    async def on_event(event):
        if event["event_type"] != "KeyPress":
            return
        # Awaiting another call from inside a handler is the point: the
        # handler runs on the loop, not on the dispatch thread.
        await vis.text(
            "You pressed: {0}".format(event["key"]), win=win, env=env, append=True
        )
        seen.set()

    vis.register_event_handler(on_event, win, env=env)
    try:
        await asyncio.wait_for(seen.wait(), timeout=wait)
        print("  handled a key press")
    except asyncio.TimeoutError:
        print("  nothing typed in {0}s, moving on".format(wait))
    finally:
        vis.clear_event_handlers(win, env=env)


DEMOS = {
    "concurrent": demo_concurrent,
    "append": demo_append,
    "images": demo_images,
    "callbacks": demo_callbacks,
}


def is_loopback(server):
    """Whether ``server`` names this machine, and so never leaves it."""
    host = urlparse(server).hostname
    if host in (None, "", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def read_password(flags):
    """Prompt for the password, rather than take it from the command line.

    An argument would sit in shell history and in every process listing. The
    login POST also sends it to whatever ``-server`` names, so a remote server
    has to be ``https``: over plain ``http`` the credentials cross the network
    in the clear.
    """
    if not flags.username:
        return None
    scheme = urlparse(flags.server).scheme
    if scheme != "https" and not is_loopback(flags.server):
        raise SystemExit(
            "refusing to send credentials to {0} over {1}; use an https "
            "server address".format(flags.server, scheme or "an unknown scheme")
        )
    return getpass.getpass("visdom password for {0}: ".format(flags.username))


async def main(flags):
    # ``create`` is a coroutine because connecting means a POST, and
    # ``__init__`` cannot await. It takes every ``Visdom`` argument.
    vis = await AsyncVisdom.create(
        port=flags.port,
        server=flags.server,
        base_url=flags.base_url,
        username=flags.username or None,
        password=read_password(flags),
        use_incoming_socket=flags.use_incoming_socket,
    )
    # The context manager calls ``shutdown``, which releases the HTTP client
    # and the worker pool. ``vis.close`` is ``Visdom.close`` -- it closes a
    # *window*, not the client.
    async with vis:
        if not await vis.check_connection():
            raise RuntimeError(
                "no visdom server at {0}:{1}; start one with "
                "`python -m visdom.server`".format(flags.server, flags.port)
            )
        names = list(DEMOS) if flags.run == "all" else [flags.run]
        for name in names:
            await DEMOS[name](vis, flags.env)
        await vis.save([flags.env])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Async demo arguments")
    parser.add_argument(
        "-port", type=int, default=8097, help="port the visdom server is running on."
    )
    parser.add_argument(
        "-server", type=str, default="http://localhost", help="Server address."
    )
    parser.add_argument("-base_url", type=str, default="/", help="Base Url.")
    parser.add_argument(
        "-username",
        type=str,
        default="",
        help="username. The password is prompted for.",
    )
    parser.add_argument(
        "-use_incoming_socket",
        action="store_true",
        help="open the backchannel, needed by the callbacks demo.",
    )
    parser.add_argument(
        "-env", type=str, default="async_demo", help="env to plot into."
    )
    parser.add_argument(
        "-run",
        type=str,
        default="all",
        choices=["all"] + list(DEMOS),
        help="demo to run. (default: 'all')",
    )
    parser.add_argument(
        "-seed", type=int, default=42, help="seed for the random data. (Default: 42)"
    )
    FLAGS = parser.parse_args()

    np.random.seed(FLAGS.seed)
    asyncio.run(main(FLAGS))
