#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import sys

assert sys.version_info[0] >= 3, "To use visdom with python 2, downgrade to v0.1.8.9"

if __name__ == "__main__":
    from visdom.server.run_server import download_scripts_and_run

    download_scripts_and_run()
