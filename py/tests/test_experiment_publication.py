#!/usr/bin/env python3

import unittest
import os
import json
import shutil
from visdom.utils.experiment_manager import ExperimentManager
from visdom.utils.latex_exporter import LaTeXExporter

class TestExperimentPublication(unittest.TestCase):
    def setUp(self):
        self.test_dir = 'test_experiments'
        self.manager = ExperimentManager(self.test_dir)
        self.exporter = LaTeXExporter()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_metadata_capture(self):
        metadata = self.manager.get_environment_metadata()
        self.assertIn('os', metadata)
        self.assertIn('python_version', metadata)
        self.assertIn('timestamp', metadata)

    def test_archive_and_load(self):
        eid = 'test_env'
        state = {eid: {'jsons': {'win1': {'type': 'plot'}}, 'reload': {}}}
        archive_file = self.manager.archive_experiment(eid, state)
        
        self.assertTrue(os.path.exists(archive_file))
        
        experiments = self.manager.list_experiments()
        self.assertEqual(len(experiments), 1)
        
        loaded = self.manager.load_experiment(experiments[0])
        self.assertEqual(loaded['eid'], eid)
        self.assertEqual(loaded['data']['jsons']['win1']['type'], 'plot')

    def test_latex_tikz_export(self):
        plot_data = {
            'title': 'Test Plot',
            'content': {
                'data': [{
                    'type': 'scatter',
                    'x': [1, 2, 3],
                    'y': [10, 20, 30],
                    'name': 'trace1'
                }]
            }
        }
        tikz = self.exporter.to_tikz(plot_data)
        self.assertIn('\\begin{tikzpicture}', tikz)
        self.assertIn('trace1', tikz)
        self.assertIn('(1, 10)', tikz)

    def test_latex_table_export(self):
        props = [
            {'name': 'Learning Rate', 'value': '0.001'},
            {'name': 'Batch Size', 'value': '32'}
        ]
        table = self.exporter.to_latex_table(props)
        self.assertIn('\\begin{tabular}', table)
        self.assertIn('Learning Rate', table)
        self.assertIn('0.001', table)

if __name__ == '__main__':
    unittest.main()
