#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import json
import tornado.escape
from visdom.server.handlers.base_handlers import BaseHandler
from visdom.utils.server_utils import check_auth, extract_eid
from visdom.utils.experiment_manager import ExperimentManager
import os

class ExperimentTrackHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.env_path = app.env_path
        self.exp_manager = ExperimentManager(os.path.join(self.env_path, "experiments"))

    @check_auth
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        eid = extract_eid(req)
        config = req.get("config", {})
        
        archive_file = self.exp_manager.archive_experiment(eid, self.state, config)
        self.write(json.dumps({"status": "success", "archive_file": archive_file}))

class ExperimentListHandler(BaseHandler):
    def initialize(self, app):
        self.env_path = app.env_path
        self.exp_manager = ExperimentManager(os.path.join(self.env_path, "experiments"))

    @check_auth
    def get(self):
        experiments = self.exp_manager.list_experiments()
        self.write(json.dumps({"experiments": experiments}))

class ExperimentDataHandler(BaseHandler):
    def initialize(self, app):
        self.env_path = app.env_path
        self.exp_manager = ExperimentManager(os.path.join(self.env_path, "experiments"))

    @check_auth
    def get(self, filename):
        data = self.exp_manager.load_experiment(filename)
        self.write(json.dumps(data))

from visdom.utils.latex_exporter import LaTeXExporter

class ExperimentExportHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.exporter = LaTeXExporter()

    @check_auth
    def post(self):
        req = tornado.escape.json_decode(self.request.body)
        eid = extract_eid(req)
        win = req.get("win")
        export_type = req.get("type", "tikz")

        if eid not in self.state or win not in self.state[eid]["jsons"]:
            self.set_status(404)
            self.write("Window not found")
            return

        plot_data = self.state[eid]["jsons"][win]
        
        if export_type == "tikz":
            output = self.exporter.to_tikz(plot_data)
        elif export_type == "table":
            output = self.exporter.to_latex_table(plot_data.get('content', []))
        else:
            self.set_status(400)
            self.write("Invalid export type")
            return

        self.write(json.dumps({"status": "success", "output": output}))
