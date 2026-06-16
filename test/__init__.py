# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import os
import sys

# Ensure local visdom source is used during testing
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "py")))
