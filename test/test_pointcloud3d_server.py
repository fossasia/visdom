#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import importlib
import unittest
import numpy as np


@unittest.skipIf(
    importlib.util.find_spec('tornado') is None,
    'tornado not installed'
)
class TestServerWindowHandler(unittest.TestCase):
    """server_utils.window() must route pointcloud3d via the content path."""

    def _make_args(self, win_id=None):
        xyz = np.zeros((1, 3), dtype=np.float32)
        import base64
        data = base64.b64encode(xyz.tobytes()).decode('ascii')
        content = {
            'version': 1,
            'transport': 'inline_base64',
            'xyz': {'dtype': 'float32', 'shape': [1, 3], 'encoding': 'base64',
                    'byte_order': 'little', 'order': 'C', 'data': data},
            'num_points_original': 1,
            'num_points_rendered': 1,
            'bounds': {'min': [0, 0, 0], 'max': [0, 0, 0],
                       'center': [0, 0, 0], 'radius': 1e-6},
        }
        return {
            'data': [{'type': 'pointcloud3d', 'content': content}],
            'win': win_id or 'test_win',
            'opts': {'title': 'test'},
        }

    def test_window_routes_pointcloud3d_via_content(self):
        from visdom.utils.server_utils import window
        args = self._make_args()
        p = window(args)
        self.assertEqual(p['type'], 'pointcloud3d')
        self.assertIn('version', p['content'])
        self.assertIn('xyz', p['content'])
        self.assertNotIn('layout', p)  # must NOT fall into Plotly branch

    def test_window_does_not_raise_key_error(self):
        from visdom.utils.server_utils import window
        args = self._make_args()
        try:
            window(args)
        except KeyError as e:
            self.fail("window() raised KeyError: {}".format(e))

    def test_window_passes_opts_through(self):
        from visdom.utils.server_utils import window
        args = self._make_args()
        args['opts']['markersize'] = 5
        args['opts']['show_axes'] = False
        p = window(args)
        self.assertIn('opts', p)
        self.assertEqual(p['opts'].get('markersize'), 5)
        self.assertEqual(p['opts'].get('show_axes'), False)

    def test_update_window_updates_opts_nested_dict(self):
        from visdom.utils.server_utils import window, update_window
        args = self._make_args()
        p = window(args)
        self.assertIn('opts', p)
        # Simulate an opts-only update (e.g. change markersize)
        update_args = {'opts': {'markersize': 8.0, 'opacity': 0.5}}
        p = update_window(p, update_args)
        self.assertEqual(p['opts'].get('markersize'), 8.0,
            'update_window must update p["opts"] nested dict, not scatter to top-level')
        self.assertEqual(p['opts'].get('opacity'), 0.5)
        # Must NOT scatter keys as top-level window attributes
        self.assertNotIn('markersize', p)
        self.assertNotIn('opacity', p)

    def test_update_window_does_not_crash_without_opts(self):
        from visdom.utils.server_utils import window, update_window
        p = window(self._make_args())
        try:
            update_window(p, {})
        except Exception as e:
            self.fail("update_window with empty args raised: {}".format(e))

    def test_update_window_preserves_existing_opts_keys(self):
        from visdom.utils.server_utils import window, update_window
        args = self._make_args()
        args['opts']['title'] = 'original'
        args['opts']['markersize'] = 3.0
        p = window(args)
        update_window(p, {'opts': {'markersize': 6.0}})
        self.assertEqual(p['opts'].get('title'), 'original',
            'update_window must preserve opts keys not included in the update')
        self.assertEqual(p['opts'].get('markersize'), 6.0)

