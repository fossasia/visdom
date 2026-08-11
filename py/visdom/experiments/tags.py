#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Normalize key/value tags used by the environment tagging API."""


MAX_TAG_LENGTH = 50
MAX_TAGS_PER_ENV = 20


def tags_to_mapping(tags) -> dict[str, str]:
    """Return model tags as a key/value mapping without discarding values."""
    return {tag.key: tag.value for tag in tags}


def normalize_tags(tags) -> dict[str, str]:
    """Validate and normalize a ``{name: value}`` tag mapping.

    Tag values are part of the experiment data model and are deliberately
    preserved. Only names are stripped because surrounding whitespace would
    otherwise create visually indistinguishable tags.
    """
    if not isinstance(tags, dict):
        raise TypeError("tags must be a dict of {name: value}")

    normalized = {}
    for raw_name, value in tags.items():
        if not isinstance(raw_name, str) or not isinstance(value, str):
            raise TypeError("tag names and values must be strings")
        name = raw_name.strip()
        if not name:
            continue
        if len(name) > MAX_TAG_LENGTH:
            raise ValueError(
                "tag names must not exceed {0} characters".format(MAX_TAG_LENGTH)
            )
        normalized[name] = value

    if len(normalized) > MAX_TAGS_PER_ENV:
        raise ValueError(
            "environments may have at most {0} tags".format(MAX_TAGS_PER_ENV)
        )
    return normalized
