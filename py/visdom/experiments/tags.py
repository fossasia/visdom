#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Validate string tags used by the environment tagging API."""


MAX_TAG_LENGTH = 50
MAX_TAGS_PER_ENV = 20


def tags_to_labels(tags):
    """Return the string names of model tags."""
    return [str(tag.key) for tag in tags]


def labels_to_tags(labels) -> dict[str, str]:
    """Validate string labels and map them to empty-valued model tags."""
    if not isinstance(labels, list) or not all(isinstance(tag, str) for tag in labels):
        raise TypeError("tags must be a list of strings")

    parsed = {}
    for raw_label in labels:
        label = raw_label.strip()
        if not label:
            continue
        if len(label) > MAX_TAG_LENGTH:
            raise ValueError(
                "tag labels must not exceed {0} characters".format(MAX_TAG_LENGTH)
            )
        parsed[label] = ""

    if len(parsed) > MAX_TAGS_PER_ENV:
        raise ValueError(
            "environments may have at most {0} tags".format(MAX_TAGS_PER_ENV)
        )
    return parsed
