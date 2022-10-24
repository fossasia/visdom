#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from os.path import expanduser

LAYOUT_FILE = "layouts.json"
DEFAULT_ENV_PATH = "%s/.visdom/" % expanduser("~")
DEFAULT_PORT = 8097
DEFAULT_HOSTNAME = "localhost"
DEFAULT_BASE_URL = "/"
MAX_SOCKET_WAIT = 15
