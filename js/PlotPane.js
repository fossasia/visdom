/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';
import Pane from './Pane';
const { sgg } = require('ml-savitzky-golay-generalized');

class PlotPane extends React.Component {
  _paneRef = null;
  _plotlyRef = null;
  _width = null;
  _height = null;

  constructor(props) {
    super(props);
    this.state = {
      maxsmoothvalue: 100,
      smoothWidgetActive: false,
      smoothvalue: 1,
    };
  }

  toggleSmoothWidget = () => {
    this.setState((state) => ({
      smoothWidgetActive: !state.smoothWidgetActive,
    }));
  };

  updateSmoothSlider = (value) => {
    this.setState((state) => ({ smoothvalue: value }));
  };

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

  shouldComponentUpdate(nextProps, nextState) {
    if (this.props.contentID !== nextProps.contentID) {
      return true;
    } else if (this.props.h !== nextProps.h || this.props.w !== nextProps.w) {
      return true;
    } else if (this.props.isFocused !== nextProps.isFocused) {
      return true;
    } else if (this.state.smoothWidgetActive !== nextState.smoothWidgetActive) {
      return true;
    } else if (this.state.smoothvalue !== nextState.smoothvalue) {
      return true;
    }

    return false;
  }

  newPlot = () => {
    var data = this.props.content.data;

    // add smoothed line plots for existing line plots
    var smooth_data = [];
    if (this.state.smoothWidgetActive) {
      smooth_data = data
        .filter((d) => d['type'] == 'scatter' && d['mode'] == 'lines')
        .map((d, dataId) => {
          var smooth_d = JSON.parse(JSON.stringify(d));
          var windowSize = 2 * this.state.smoothvalue + 1;

          // remove legend of smoothed plot
          smooth_d.showlegend = false;

          // turn off smoothing for smoothvalue of 3 or too small arrays
          if (windowSize < 5 || smooth_d.x.length <= 5) {
            d.opacity = 1.0;

            return smooth_d;
          }

          // savitzky golay requires the window size to be ≥ 5
          windowSize = Math.max(windowSize, 5);

          // window size needs to be odd
          if (smooth_d.x.length % 2 == 0)
            windowSize = Math.min(windowSize, smooth_d.x.length - 1);
          else windowSize = Math.min(windowSize, smooth_d.x.length);
          smooth_d.y = sgg(smooth_d.y, smooth_d.x, { windowSize: windowSize });

          // adapt color & transparency
          d.opacity = 0.35;
          smooth_d.opacity = 1.0;
          smooth_d.marker.line.color = 0;

          return smooth_d;
        });

      // pad data in case we have some smoothed lines
      // this is to let plotly use the same colors if no colors are given by the user
      if (smooth_data.length > 0) {
        data = Array.from(data);
        let num_to_fill = 10 - (data.length % 10);
        for (let i = 0; i < num_to_fill; i++) data.push({});
        console.log(data);
      }
    } else
      this.props.content.data
        .filter((data) => data['type'] == 'scatter' && data['mode'] == 'lines')
        .map((d, dataId) => {
          d.opacity = 1.0;
        });

    Plotly.newPlot(
      this.props.contentID,
      data.concat(smooth_data),
      this.props.content.layout,
      { showLink: true, linkText: 'Edit' }
    );
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
    // check if data can be smoothed
    var contains_line_plots = this.props.content.data.some((data, dataId) => {
      return data['type'] == 'scatter' && data['mode'] == 'lines';
    });

    var smooth_widget_button = '';
    var smooth_widget = '';
    if (contains_line_plots) {
      smooth_widget_button = (
        <button
          key="smooth_widget_button"
          title="smooth lines"
          onClick={this.toggleSmoothWidget}
          className={
            this.state.smoothWidgetActive ? 'pull-right active' : 'pull-right'
          }
        >
          ~
        </button>
      );
      if (this.state.smoothWidgetActive) {
        smooth_widget = (
          <div className="widget" key="smooth_widget">
            <div style={{ display: 'flex' }}>
              <span>Smoothing:&nbsp;&nbsp;</span>
              <input
                type="range"
                min="1"
                max={this.state.maxsmoothvalue}
                value={this.state.smoothvalue}
                onInput={(ev) => this.updateSmoothSlider(ev.target.value)}
              />
              <span>&nbsp;&nbsp;{this.state.selected}&nbsp;&nbsp;</span>
            </div>
          </div>
        );
      }
    }

    return (
      <Pane
        {...this.props}
        handleDownload={this.handleDownload}
        ref={(ref) => (this._paneRef = ref)}
        barwidgets={[smooth_widget_button]}
        widgets={[smooth_widget]}
        enablePropertyList
      >
        <div
          id={this.props.contentID}
          style={{ height: '100%', width: '100%' }}
          className="plotly-graph-div"
          ref={(ref) => (this._plotlyRef = ref)}
        />
      </Pane>
    );
  }
}

export default PlotPane;
