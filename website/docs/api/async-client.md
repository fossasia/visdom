---
sidebar_position: 8
title: Async Client
description: AsyncVisdom — the awaitable front end to the Visdom Python client
---

# Async Client

`visdom.async_client.AsyncVisdom` is an awaitable front end to the same client. It is for callers that already run an event loop, or that want several plots in flight at once. `visdom.Visdom` is unchanged and remains the way to use Visdom from ordinary synchronous code — importing the async client changes nothing for existing users.

```python
import asyncio
import numpy as np
from visdom.async_client import AsyncVisdom

async def main():
    vis = await AsyncVisdom.create(server="http://localhost", port=8097)
    async with vis:
        await asyncio.gather(
            vis.line(Y=np.random.rand(20), win="a"),
            vis.line(Y=np.random.rand(20), win="b"),
        )

asyncio.run(main())
```

Every plotting method of `Visdom` is available under the same name, with the same arguments and the same return value — as a coroutine.

## How it works

Nothing is reimplemented. The plot methods run as the synchronous code they already are, on a thread pool the client owns, and only the request itself is asynchronous.

That shape is deliberate: several methods (`scatter`, `image`) need the *result* of a mid-method preflight before they can build the rest of their payload, and a synchronous body cannot await. Running the body on a worker and awaiting only the request keeps every plot method byte-for-byte identical to the synchronous one, while your event loop stays free. It also means the CPU-heavy encodes — PNG, base64, `savefig` — end up off the loop at no extra cost.

Transport is tornado's `AsyncHTTPClient`, which Visdom already depends on for the server, so the async client adds no dependency.

## Creating and closing

```python
vis = await AsyncVisdom.create(server="http://localhost", port=8097, env="main")
```

`create` is a coroutine because connecting means a POST, and `__init__` cannot await. It accepts every [`Visdom` argument](./overview.md#visdom-arguments-python-only), plus:

| Argument | Default | Description |
| --- | --- | --- |
| `max_concurrency` | `10` | How many calls may be in flight at once. Sizes the client's own thread pool and supplies the default for tornado's `max_clients`, so a worker thread only exists for a request tornado is willing to start immediately. An explicit `max_clients` takes precedence, and the two limits then differ |

:::note `shutdown` closes the client, `close` closes a window
`close` is `Visdom.close` and keeps its usual meaning, so the method that releases the HTTP client and the worker pool is `shutdown()`. Using the client as an async context manager — `async with vis:` — calls it for you. Calling it twice is safe.
:::

## Defaults that differ from `Visdom`

| Option | `Visdom` | `AsyncVisdom` | Why |
| --- | --- | --- | --- |
| `use_incoming_socket` | `True` | `False` | Most async callers never register a handler, and a backchannel costs a held-open connection plus a thread to run handlers on |
| `use_preflight_checks` | `True` | `False` | An async client is new code talking to a server that understands `layout_create`, so an append costs one request instead of two |

Pass either explicitly to get the synchronous behavior back — `use_preflight_checks=True` is what you want against a server older than the create-on-append layout support.

## Concurrency

Concurrency is yours to ask for: `asyncio.gather` runs the calls on separate worker threads against one shared inner client.

```python
await asyncio.gather(
    *(vis.image(frame, win=f"cam_{i}") for i, frame in enumerate(frames))
)
```

:::warning Target distinct windows
The wrapped client is no more thread-safe than the synchronous one. Concurrent calls that write the same window race each other.
:::

## Event handlers

Pass `use_incoming_socket=True` (or `use_polling=True` for the HTTP fallback) and register handlers as usual. The backchannel is asyncio too — a task on your loop feeds the same seam the synchronous client feeds.

```python
vis = await AsyncVisdom.create(use_incoming_socket=True)
win = await vis.text("Type here.")

async def on_event(event):
    if event["event_type"] == "KeyPress":
        await vis.text(f"You pressed: {event['key']}", win=win, append=True)

vis.register_event_handler(on_event, win)
```

`register_event_handler` is not a coroutine: registration is bookkeeping and never reaches the server. The handler may be a plain function or a coroutine function, and where its body runs differs:

- **A plain function** runs on the client's own single dispatch thread (`visdom-async-events`), off your loop. It must not block for long, and it cannot await.
- **A coroutine function** is wrapped: only the wrapper occupies the dispatch thread, blocking it while the coroutine body runs on your loop. That is why the body can await further calls on the same client.

Either way one dispatch thread serves every handler, so handlers run one at a time, in arrival order — a slow one delays later events but nothing else.

## Limitations

- **No HTTP proxies.** `create` raises `NotImplementedError` for `proxies`, `http_proxy_host` and `http_proxy_port`: tornado's `AsyncHTTPClient` has no proxy support without `pycurl`. Use `Visdom` behind a proxy.
- **One loop per client.** The client is bound to the loop it was created on; do not share it across loops.

## Benchmarks

Measured on loopback over 300 `line(update='append')` calls — the path profiled in [issue #771](https://github.com/fossasia/visdom/issues/771):

| Client | plots/s | p50 | p95 |
| --- | --- | --- | --- |
| `Visdom`, preflight on (default) | 198 | 5.00 ms | 5.73 ms |
| `Visdom`, `use_preflight_checks=False` | 304 | 3.32 ms | 4.09 ms |
| `AsyncVisdom`, awaited serially | 235 | 4.24 ms | 4.87 ms |
| `AsyncVisdom`, 8 concurrent | 410 | 13.19 ms | 18.33 ms |

Requests halve exactly once the preflight is off. Throughput does not quite double because on loopback the preflight is the cheaper of the two round trips; over a real network the two cost the same.

## Runnable demo

`example/async_demo.py` runs all of the above against a live server:

```bash
python example/async_demo.py -run all
python example/async_demo.py -run callbacks -use_incoming_socket
```
