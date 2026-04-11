/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useRef, useState } from 'react';
const { usePrevious } = require('../util');
import Pane from './Pane';
const { sgg } = require('ml-savitzky-golay-generalized');

var PlotPane = (props) => {
  const { contentID, content, type, show_slider } = props;

  // state varibles
  // --------------
  const plotlyRef = useRef();
  const previousContent = usePrevious(content);
  const prevSelected = usePrevious(actualSelected);
  const maxsmoothvalue = 100;
  const [smoothWidgetActive, setSmoothWidgetActive] = useState(false);
  const [smoothvalue, setSmoothValue] = useState(1);
  const [actualSelected, setActualSelected] = useState(props.selected || 0);

  useEffect(() => {
    setActualSelected(props.selected || 0);
  }, [props.selected]);

  // private events
  // -------------
  const toggleSmoothWidget = () => {
    setSmoothWidgetActive(!smoothWidgetActive);
  };
  const updateSmoothSlider = (value) => {
    setSmoothValue(value);
  };
  const updateHistorySlider = (evt) => {
    setActualSelected(parseInt(evt.target.value));
  };
  const handleDownload = () => {
    Plotly.downloadImage(plotlyRef.current, {
      format: 'svg',
      filename: contentID,
    });
  };

  // events
  // ------
  useEffect(() => {
    const isHistory = type === 'plot_history';
    const currentFrame = isHistory
      ? content[actualSelected] || content[0]
      : content;
    const previousFrame =
      isHistory && previousContent
        ? previousContent[prevSelected != null ? prevSelected : 0] ||
          previousContent[0]
        : previousContent;

    if (previousFrame) {
      // Retain trace visibility between old and new plots
      let trace_visibility_by_name = {};
      let trace_idx = null;
      for (trace_idx in previousFrame.data) {
        let trace = previousFrame.data[trace_idx];
        trace_visibility_by_name[trace.name] = trace.visible;
      }
      for (trace_idx in currentFrame.data) {
        let trace = currentFrame.data[trace_idx];
        trace.visible = trace_visibility_by_name[trace.name];
      }

      // Copy user modified zooms
      let old_x = previousFrame.layout.xaxis;
      let new_x = currentFrame.layout.xaxis;
      let new_range_set = new_x !== undefined && new_x.autorange === false;
      if (old_x !== undefined && old_x.autorange === false && !new_range_set) {
        // Take the old x axis layout if changed
        currentFrame.layout.xaxis = old_x;
      }
      let old_y = previousFrame.layout.yaxis;
      let new_y = currentFrame.layout.yaxis;
      new_range_set = new_y !== undefined && new_y.autorange === false;
      if (old_y !== undefined && old_y.autorange === false && !new_range_set) {
        // Take the old y axis layout if changed
        currentFrame.layout.yaxis = old_y;
      }
    }

    newPlot(currentFrame);
  }, [
    content,
    actualSelected,
    smoothWidgetActive,
    smoothvalue,
    props.version,
    type,
  ]);

  // rendering
  // ---------

  const newPlot = (frame) => {
    frame = frame || content;
    var data = frame.data;

    // add smoothed line plots for existing line plots
    var smooth_data = [];
    if (smoothWidgetActive) {
      smooth_data = data
        .filter((d) => d['type'] == 'scatter' && d['mode'] == 'lines')
        .map((d) => {
          var smooth_d = JSON.parse(JSON.stringify(d));
          var windowSize = 2 * smoothvalue + 1;

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
          smooth_d.y = sgg(smooth_d.y, smooth_d.x, {
            windowSize: windowSize,
          });

          // adapt color & transparency
          d.opacity = 0.35;
          smooth_d.opacity = 1.0;
          smooth_d.marker.line.color = 0;

          return smooth_d;
        });

      // pad data in case we have some smoothed lines
      // (lets plotly use the same colors if no colors are given by the user)
      if (smooth_data.length > 0) {
        data = Array.from(data);
        let num_to_fill = 10 - (data.length % 10);
        for (let i = 0; i < num_to_fill; i++) data.push({});
      }
    } else
      frame.data
        .filter((data) => data['type'] == 'scatter' && data['mode'] == 'lines')
        .map((d) => {
          d.opacity = 1.0;
        });

    // required for Plotly.react to register the update
    frame.layout.datarevision =
      type === 'plot_history'
        ? props.version + '-' + actualSelected
        : props.version;

    // draw / redraw plot with layout-options
    Plotly.react(contentID, data.concat(smooth_data), frame.layout, {
      showLink: true,
      linkText: 'Edit',
    });
  };

  const frameForRender =
    type === 'plot_history'
      ? content[actualSelected] || content[0]
      : content;

  // check if data can be smoothed
  var contains_line_plots = frameForRender.data.some((data) => {
    return data['type'] == 'scatter' && data['mode'] == 'lines';
  });

  var smooth_widget_button = '';
  var smooth_widget = '';
  if (contains_line_plots) {
    smooth_widget_button = (
      <button
        key="smooth_widget_button"
        title="smooth lines"
        onClick={toggleSmoothWidget}
        className={smoothWidgetActive ? 'pull-right active' : 'pull-right'}
      >
        ~
      </button>
    );
    if (smoothWidgetActive) {
      smooth_widget = (
        <div className="widget" key="smooth_widget">
          <div style={{ display: 'flex' }}>
            <span>Smoothing:&nbsp;&nbsp;</span>
            <input
              type="range"
              min="1"
              max={maxsmoothvalue}
              value={smoothvalue}
              onInput={(ev) => updateSmoothSlider(ev.target.value)}
            />
            <span>&nbsp;&nbsp;&nbsp;&nbsp;</span>
          </div>
        </div>
      );
    }
  }

  let history_caption = null;
  let history_slider = null;
  if (type === 'plot_history' && Array.isArray(content)) {
    if (frameForRender.caption) {
      history_caption = (
        <span className="widget" key="plot_history_caption">
          {frameForRender.caption}
        </span>
      );
    }
    if (show_slider && content.length > 1) {
      history_slider = (
        <div className="widget" key="plot_history_slider">
          <div style={{ display: 'flex' }}>
            <span>Iteration:&nbsp;&nbsp;</span>
            <input
              type="range"
              min="0"
              max={content.length - 1}
              value={actualSelected}
              onChange={updateHistorySlider}
            />
            <span>&nbsp;&nbsp;{actualSelected}&nbsp;&nbsp;</span>
          </div>
        </div>
      );
    }
  }

  return (
    <Pane
      {...props}
      handleDownload={handleDownload}
      barwidgets={[smooth_widget_button]}
      widgets={[smooth_widget, history_caption, history_slider]}
      enablePropertyList
    >
      <div
        id={contentID}
        style={{ height: '100%', width: '100%' }}
        className="plotly-graph-div"
        ref={plotlyRef}
      />
    </Pane>
  );
};

// prevent rerender unless we know we need one
// (previously known as shouldComponentUpdate)
PlotPane = React.memo(PlotPane, (props, nextProps) => {
  if (props.contentID !== nextProps.contentID) return false;
  else if (props.h !== nextProps.h || props.w !== nextProps.w) return false;
  else if (props.isFocused !== nextProps.isFocused) return false;
  return true;
});

export default PlotPane;
