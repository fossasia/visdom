#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Renders what an instance knows about its workspaces in Prometheus' text format.

Written out by hand rather than through a client library. The exposition format
is a few lines of text, and a server that has managed without a metrics
dependency should not take one on to emit them.

Attribution is the part that makes this worth having. A visdom process serves
many workspaces at once, so its own CPU and memory cannot be divided between
them after the fact. These numbers are counted where the work happens instead,
against the workspace that caused it.
"""

# Prometheus counts anything ending in _total as a counter, which resets to zero
# when the process restarts and is expected to. Everything else here is a gauge:
# a reading taken now, meaningless to add up over time.
_FAMILIES = (
    (
        "visdom_workspace_writes_total",
        "counter",
        "Environment writes attributed to this workspace.",
    ),
    (
        "visdom_workspace_broadcasts_total",
        "counter",
        "Messages pushed to this workspace's viewers.",
    ),
    (
        "visdom_workspace_broadcast_bytes_total",
        "counter",
        "Bytes pushed to this workspace's viewers.",
    ),
    ("visdom_workspace_viewers", "gauge", "Sockets currently watching this workspace."),
    ("visdom_workspace_writers", "gauge", "Sources currently feeding this workspace."),
    (
        "visdom_workspace_stored_bytes",
        "gauge",
        "Size on disk of this workspace's environments.",
    ),
    (
        "visdom_workspace_last_write_timestamp_seconds",
        "gauge",
        "When this workspace was last written to.",
    ),
)


def escape_label(value):
    """Escape a label value, which may be a slug someone else chose.

    Prometheus gives backslash, double quote and newline meaning inside a label,
    so a value carrying one would produce a line that does not parse, or worse
    one that parses as something other than intended.
    """
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(samples):
    """Render one line per workspace per family, grouped as Prometheus expects.

    Each family is emitted once with its HELP and TYPE and then all of its
    values, rather than everything about one workspace together: scrapers are
    entitled to reject a family that appears in more than one place.

    A workspace missing a value is left out of that family rather than reported
    as zero, because a size nobody has measured and a size of zero are different
    answers and only one of them is true.
    """
    lines = []
    for name, kind, help_text in _FAMILIES:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        for sample in samples:
            value = sample.get(name)
            if value is None:
                continue
            labels = 'workspace="%s",slug="%s"' % (
                escape_label(sample.get("workspace_id", "")),
                escape_label(sample.get("slug") or ""),
            )
            lines.append(f"{name}{{{labels}}} {value}")
    return "\n".join(lines) + "\n"


def sample_from_activity(entry):
    """Turn one workspace's activity entry into the values a scrape wants.

    The activity endpoint already answers per workspace and already merges the
    disk pass into the socket pass, so this reads what is there rather than
    gathering it a second way and risking two sources that disagree.
    """
    return {
        "workspace_id": entry.get("workspace_id", ""),
        "slug": entry.get("slug"),
        "visdom_workspace_writes_total": entry.get("writes"),
        "visdom_workspace_broadcasts_total": entry.get("broadcasts"),
        "visdom_workspace_broadcast_bytes_total": entry.get("broadcast_bytes"),
        "visdom_workspace_viewers": entry.get("viewers"),
        "visdom_workspace_writers": entry.get("writers"),
        "visdom_workspace_stored_bytes": entry.get("bytes"),
        "visdom_workspace_last_write_timestamp_seconds": entry.get("last_active_at"),
    }
