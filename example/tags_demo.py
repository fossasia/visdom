#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Demo script to showcase the Experiment Tagging system.
This demo shows how to set, append, and retrieve tags for different environments.
"""

import time
from visdom import Visdom

def run_tags_demo():
    print("Connecting to Visdom...")
    viz = Visdom()

    if not viz.check_connection():
        print("Visdom server not found. Please start it with 'python -m visdom.server'")
        return

    env1 = "tag_demo_env_1"
    env2 = "tag_demo_env_2"

    print(f"\n1. Setting initial tags for {env1}...")
    # Set explicit tags
    viz.set_tags(["baseline", "project-x"], env=env1)
    
    # Add some content so the environment stays visible
    viz.text("This environment has tags: baseline, project-x", env=env1)

    print(f"2. Appending a new tag to {env1}...")
    # Append tags without overwriting existing ones
    viz.set_tags(["version-1.0"], env=env1, append=True)

    print(f"3. Setting tags for {env2}...")
    viz.set_tags(["experimental", "low-lr"], env=env2)
    viz.text("This environment has tags: experimental, low-lr", env=env2)

    print("\n4. Retrieving tags via SDK...")
    tags1 = viz.get_tags(env=env1)
    tags2 = viz.get_tags(env=env2)

    print(f"Env '{env1}' tags: {tags1}")
    print(f"Env '{env2}' tags: {tags2}")

    print("\nDemo completed!")
    print("You can now open the Visdom UI in your browser and:")
    print("1. Find these environments in the 'Environment' dropdown.")
    print("2. Hover over them to see the tags.")
    print("3. Click the 'Tag' icon (Manage Tags) to edit them manually.")

if __name__ == '__main__':
    run_tags_demo()
