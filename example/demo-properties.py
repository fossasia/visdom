# Copyright 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from visdom import Visdom
import numpy as np
import math
import os.path
import getpass
import time
from sys import platform as _platform
from six.moves import urllib


try:
    viz = Visdom()

    startup_sec = 1
    while not viz.check_connection() and startup_sec > 0:
        time.sleep(0.1)
        startup_sec -= 0.1
    assert viz.check_connection(), 'No connection could be formed quickly'

    # text window with Callbacks
    txt = 'This is a write demo notepad. Type below. Delete clears text:<br>'
    callback_text_window = viz.text(txt)

    def type_callback(event):
        if event['event_type'] == 'KeyPress':
            curr_txt = event['pane_data']['content']
            if event['key'] == 'Enter':
                curr_txt += '<br>'
            elif event['key'] == 'Backspace':
                curr_txt = curr_txt[:-1]
            elif event['key'] == 'Delete':
                curr_txt = txt
            elif len(event['key']) == 1:
                curr_txt += event['key']
            viz.text(curr_txt, win=callback_text_window)

    viz.register_event_handler(type_callback, callback_text_window)

    # Properties window
    properties = [
        {'type': 'text', 'name': 'Text input', 'value': 'initial'},
        {'type': 'number', 'name': 'Number input', 'value': '12'},
        {'type': 'button', 'name': 'Button', 'value': 'Start'},
        {'type': 'checkbox', 'name': 'Checkbox', 'value': True},
        {'type': 'select', 'name': 'Select', 'value': 1, 'values': ['Red', 'Green', 'Blue']},
    ]

    properties_window = viz.properties(properties)

    def properties_callback(event):
        if event['event_type'] == 'PropertyUpdate':
            prop_id = event['propertyId']
            value = event['value']
            if prop_id == 0:
                new_value = value + '_updated'
            elif prop_id == 1:
                new_value = value + '0'
            elif prop_id == 2:
                new_value = 'Stop' if properties[prop_id]['value'] == 'Start' else 'Start'
            else:
                new_value = value
            properties[prop_id]['value'] = new_value
            viz.properties(properties, win=properties_window)
            viz.text(f"Updated: {properties[event['propertyId']]['name']} => {str(event['value'])}",
                     win=callback_text_window, append=True)

    viz.register_event_handler(properties_callback, properties_window)

    try:
        input = raw_input  # for Python 2 compatibility
    except NameError:
        pass
    input('Waiting for callbacks, press enter to quit.')
except BaseException as e:
    print(
        "The visdom experienced an exception while running: {}\n"
        "The demo displays up-to-date functionality with the GitHub version, "
        "which may not yet be pushed to pip. Please upgrade using "
        "`pip install -e .` or `easy_install .`\n"
        "If this does not resolve the problem, please open an issue on "
        "our GitHub.".format(repr(e))
    )
