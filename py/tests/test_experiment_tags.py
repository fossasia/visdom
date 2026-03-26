#!/usr/bin/env python3

from visdom.utils.server_utils import (
    add_tags,
    get_experiments_by_tag,
    remove_tag,
)


def test_add_tags_on_legacy_env_structure():
    # Legacy envs may not have a "tags" key; this should still work.
    state = {"exp1": {"jsons": {}, "reload": {}}}
    updated_tags = add_tags(state, "exp1", ["cnn", "resnet"])

    assert updated_tags == ["cnn", "resnet"]
    assert state["exp1"]["tags"] == ["cnn", "resnet"]


def test_get_experiments_by_tag_filters_expected_envs():
    state = {
        "exp1": {"jsons": {}, "reload": {}, "tags": ["cnn", "vision"]},
        "exp2": {"jsons": {}, "reload": {}, "tags": ["nlp"]},
        "exp3": {"jsons": {}, "reload": {}},
    }

    filtered = get_experiments_by_tag(state, "cnn")

    assert filtered == ["exp1"]


def test_remove_tag_updates_tag_list():
    state = {"exp1": {"jsons": {}, "reload": {}, "tags": ["cnn", "vision"]}}

    updated_tags = remove_tag(state, "exp1", "cnn")

    assert updated_tags == ["vision"]
    assert state["exp1"]["tags"] == ["vision"]
