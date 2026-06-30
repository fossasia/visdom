#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import sys

if sys.version_info < (3, 12):
    raise RuntimeError("Visdom requires Python 3.12 or newer.")

if __name__ == "__main__":
    from visdom.server.run_server import download_scripts_and_run

    download_scripts_and_run()
