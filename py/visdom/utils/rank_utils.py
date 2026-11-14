#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import os
import sys


def _process_group_rank():
    dist = sys.modules.get("torch.distributed")
    if dist is not None and dist.is_available() and dist.is_initialized():
        return dist.get_rank()
    return None


def _environment_rank():
    for key in ("RANK", "SLURM_PROCID"):
        try:
            return int(os.environ[key])
        except (KeyError, ValueError):
            continue
    return None


def is_main_process():
    """Return True if this is global rank 0 of a distributed job.

    An initialized torch.distributed process group decides first, so
    launchers that set no environment variables (mp.spawn) still work.
    Otherwise the launcher's RANK or SLURM_PROCID is used. LOCAL_RANK is
    ignored on purpose: it is 0 on every node, so it would name one
    process per node instead of one per job. With no rank information
    at all the process is the only one, so it is the main process.

    The answer is read on every call because torchrun can hand out new
    ranks after an elastic restart.
    """
    rank = _process_group_rank()
    if rank is None:
        rank = _environment_rank()
    return rank is None or rank <= 0
