#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Where does the time go when a client sends an image?

Three costs, all charged per pixel rather than per call, so they are the ones
that grow with the picture:

* the PNG encode itself, which is PIL's default ``compress_level=6`` unless
  ``opts.compresslevel`` says otherwise;
* the base64 wrapping of whatever that produced;
* and, for a float image, the scaling pass that finds its range and clips it
  into bytes.

``images`` adds a fourth: it tiles the batch into one grid and sends *that*
through ``image``, so the grid's dtype decides whether the scaling pass runs
at all.

    python example/benchmarks/media_encode.py
    python example/benchmarks/media_encode.py --sizes 256,512,1024

``--sizes`` are image edges in pixels, not point counts. Sizes are squared, so
the default three already span a 16x range in pixel count.
"""

import base64
from io import BytesIO

import _harness as harness

DEFAULT_EDGES = "128,512,1024"
LEVELS = (0, 1, 6, 9)


def photo(edge):
    """A smooth, correlated-channel image -- what a camera or a plot produces.

    Random pixels would be the wrong fixture here: noise is incompressible, so
    every compression level returns the same size in the same time and the
    whole table reads flat. Real images have structure, which is exactly what
    the level trades time against.
    """
    import numpy as np

    rows, cols = np.mgrid[0:edge, 0:edge]
    luminance = (
        np.sin(cols / 37.0) * 0.3 + np.cos(rows / 23.0) * 0.3 + 0.5
    ) * 255 + np.random.default_rng(0).normal(0, 14, (edge, edge))
    return np.clip(
        np.stack([luminance * 1.05, luminance * 0.92, luminance * 1.12]), 0, 255
    ).astype("uint8")


def tiles(img, count=16):
    """A batch of the same picture, which is what ``images`` tiles into a grid.

    The grid is the interesting part: it is one image several times the size of
    its tiles, so whatever ``image`` charges per pixel, ``images`` charges on
    the whole mosaic. Sixteen half-size tiles make a grid of roughly four times
    the pixels of ``img``, so this row is comparable with the ones above it.
    """
    import numpy as np

    half = img[:, ::2, ::2]
    return np.stack([half] * count)


def encode_png(img, level):
    """The ``image()`` tail: PIL save plus the base64 the data URI carries."""
    import numpy as np
    from PIL import Image

    buf = BytesIO()
    args = {} if level is None else {"compress_level": level}
    Image.fromarray(np.transpose(img, (1, 2, 0)), mode="RGB").save(
        buf, format="PNG", **args
    )
    encoded = buf.getvalue()
    base64.b64encode(encoded)
    encode_png.payload = len(encoded)
    return encoded


def main():
    args = harness.arg_parser(
        __doc__.splitlines()[0], sizes=DEFAULT_EDGES, repeat=10
    ).parse_args()

    client = harness.offline_client()
    rows = []
    for edge in harness.parse_sizes(args):
        img = photo(edge)
        label = "%dx%d" % (edge, edge)

        levels = {}
        for level in LEVELS:
            result = harness.measure(
                lambda level=level: encode_png(img, level), args.repeat, args.warmup
            )
            levels[level] = (result, encode_png.payload)
        default = levels[6][0].p50  # PIL's default, so what an unset opt costs
        for level, (result, payload) in levels.items():
            rows.append(
                (
                    label,
                    "level %d" % level,
                    "%.1f" % result.p50,
                    "%.1f" % result.p95,
                    "%.0f" % (payload / 1024.0),
                    "%.2fx" % (default / result.p50) if result.p50 else "-",
                )
            )

        # Whole calls, for scale. A float image pays the scaling pass on top of
        # the encode; a uint8 one does not, which is the difference `images`
        # inherits from the dtype of the grid it builds.
        float_img = img.astype("float64") / 255.0
        batch = tiles(img)
        whole = (
            ("image uint8", lambda: client.image(img)),
            ("image float", lambda: client.image(float_img)),
            ("images batch", lambda: client.images(batch)),
        )
        for name, call in whole:
            result = harness.measure(call, max(1, args.repeat // 2), args.warmup // 4)
            rows.append(
                (label, name, "%.1f" % result.p50, "%.1f" % result.p95, "-", "-")
            )

    harness.table(
        ["image", "level / path", "p50 ms", "p95 ms", "payload KB", "vs level 6"], rows
    )


if __name__ == "__main__":
    main()
