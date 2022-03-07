/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';
const Pane = require('./Pane');

class PlotPane extends React.Component {
  _paneRef = null;
  _plotlyRef = null;
  _width = null;
  _height = null;

  componentDidMount() {
    this.newPlot();
  }

  componentDidUpdate(prevProps) {
    // Retain trace visibility between old and new plots
    let trace_visibility_by_name = {};
    let trace_idx = null;
    for (trace_idx in prevProps.content.data) {
      let trace = prevProps.content.data[trace_idx];
      trace_visibility_by_name[trace.name] = trace.visible;
    }
    for (trace_idx in this.props.content.data) {
      let trace = this.props.content.data[trace_idx];
      trace.visible = trace_visibility_by_name[trace.name];
    }

    // Copy user modified zooms
    let old_x = prevProps.content.layout.xaxis;
    let new_x = this.props.content.layout.xaxis;
    let new_range_set = new_x !== undefined && new_x.autorange === false;
    if (old_x !== undefined && old_x.autorange === false && !new_range_set) {
      // Take the old x axis layout if changed
      this.props.content.layout.xaxis = old_x;
    }
    let old_y = prevProps.content.layout.yaxis;
    let new_y = this.props.content.layout.yaxis;
    new_range_set = new_y !== undefined && new_y.autorange === false;
    if (old_y !== undefined && old_y.autorange === false && !new_range_set) {
      // Take the old y axis layout if changed
      this.props.content.layout.yaxis = old_y;
    }
    this.newPlot();
  }

  shouldComponentUpdate(nextProps) {
    if (this.props.contentID !== nextProps.contentID) {
      return true;
    } else if (this.props.h !== nextProps.h || this.props.w !== nextProps.w) {
      return true;
    } else if (this.props.isFocused !== nextProps.isFocused) {
      return true;
    }
    return false;
  }

  newPlot = () => {
    // determine data based on window (compare) settings
    if (
      !this.props.has_compare ||
      (this.props.compare_view_mode && this.props.compare_view_mode == 'select')
    )
      var content = this.props.content;
    // merge mode (for scatter plots)
    else {
      var layout = this.props.compare_content[0].layout;
      layout.showlegend = true;

      // first merge list of data-lists into flat data-list
      var data = this.props.compare_content
        .map(function(content) {
          return content.data;
        })
        .flat();

      // use the modified compare_name as labels
      data.forEach(function(val) {
        val.name = val.compare_name;
      });

      var content = {
        layout: layout,
        data: data,
      };
    }

    Plotly.newPlot(this.props.contentID, content.data, content.layout, {
      showLink: true,
      linkText: 'Edit',
    });
  };

  handleDownload = () => {
    Plotly.downloadImage(this._plotlyRef, {
      format: 'svg',
      filename: this.props.contentID,
    });
  };

  resize = () => {
    this.componentDidUpdate();
  };

  render() {
    let widgets = [];

    return (
      <Pane
        {...this.props}
        handleDownload={this.handleDownload}
        ref={ref => (this._paneRef = ref)}
        widgets={widgets}
      >
        <div
          id={this.props.contentID}
          style={{ height: '100%', width: '100%' }}
          className="plotly-graph-div"
          ref={ref => (this._plotlyRef = ref)}
        />
      </Pane>
    );
  }
}

module.exports = PlotPane;
