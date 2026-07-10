/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useContext, useEffect, useRef, useState } from 'react';
const { usePrevious } = require('../util');
import ApiContext from '../api/ApiContext';
import Pane from './Pane';
const { sgg } = require('ml-savitzky-golay-generalized');

var PlotPane = (props) => {
  const { contentID, type, selected } = props;
  const isHistory = type === 'plot_history';

  // state variables
  // --------------
  const plotlyRef = useRef();
  const maxsmoothvalue = 100;
  const [smoothWidgetActive, setSmoothWidgetActive] = useState(false);
  const [smoothvalue, setSmoothValue] = useState(1);
  const [actualSelected, setActualSelected] = useState(
    isHistory ? selected || 0 : 0
  );
  const { sendPlotLayoutUpdate } = useContext(ApiContext);
  const layoutUpdateTimeout = useRef(null);

  const content = isHistory
    ? props.content[Math.min(actualSelected, props.content.length - 1)]
    : props.content;

  const previousContent = usePrevious(content);

  useEffect(() => {
    if (isHistory && selected !== undefined) {
      setActualSelected(selected);
    }
  }, [selected]);

  // private events
  // -------------
  const toggleSmoothWidget = () => {
    setSmoothWidgetActive(!smoothWidgetActive);
  };
  const updateSmoothSlider = (value) => {
    setSmoothValue(value);
  };
  const handleDownload = () => {
    Plotly.downloadImage(plotlyRef.current, {
      format: 'svg',
      filename: contentID,
    });
  };

  const handleMetadataExport = () => {
    const graph = plotlyRef.current;
    const metadata = {
      data: graph?.data ?? content?.data ?? [],
      layout: graph?.layout ?? content?.layout ?? {},
    };
    const json = JSON.stringify(metadata, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${contentID}_metadata.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  };

  const updateHistorySlider = (ev) => {
    setActualSelected(parseInt(ev.target.value));
  };

  // events
  // ------
  const isDisplayed = (el) =>
    !!(el && el.offsetWidth > 0 && el.offsetHeight > 0);
  useEffect(() => {
    const plotElement = plotlyRef.current;
    if (!plotElement) return;

    const resizeObserver = new ResizeObserver(() => {
      if (plotElement._fullLayout && isDisplayed(plotElement)) {
        Plotly.Plots.resize(plotElement);
      }
    });

    resizeObserver.observe(plotElement);
    return () => resizeObserver.disconnect();
  }, []);
  useEffect(() => {
    if (previousContent && content) {
      // Retain trace visibility between old and new plots
      let trace_visibility_by_name = {};
      let trace_idx = null;
      for (trace_idx in previousContent.data) {
        let trace = previousContent.data[trace_idx];
        trace_visibility_by_name[trace.name] = trace.visible;
      }
      for (trace_idx in content.data) {
        let trace = content.data[trace_idx];
        trace.visible = trace_visibility_by_name[trace.name];
      }

      // Copy user modified zooms
      let old_x = previousContent.layout.xaxis;
      let new_x = content.layout.xaxis;
      let new_range_set = new_x !== undefined && new_x.autorange === false;
      if (old_x !== undefined && old_x.autorange === false && !new_range_set) {
        // Take the old x axis layout if changed
        content.layout.xaxis = old_x;
      }
      let old_y = previousContent.layout.yaxis;
      let new_y = content.layout.yaxis;
      new_range_set = new_y !== undefined && new_y.autorange === false;
      if (old_y !== undefined && old_y.autorange === false && !new_range_set) {
        // Take the old y axis layout if changed
        content.layout.yaxis = old_y;
      }
    }

    newPlot();
  });

  useEffect(() => {
    const plotElement = plotlyRef.current;
    if (!plotElement) return;

    const handleRelayout = (eventdata) => {
      const touchedShapes = Object.keys(eventdata).some((k) =>
        k.includes('shapes')
      );
      if (!touchedShapes) return;

      clearTimeout(layoutUpdateTimeout.current);
      layoutUpdateTimeout.current = setTimeout(() => {
        const shapes = plotElement.layout?.shapes || [];

        if (content && content.layout) {
          content.layout.shapes = shapes;
        }

        sendPlotLayoutUpdate(
          props.envID,
          props.id,
          { shapes },
          isHistory ? actualSelected : undefined
        );
      }, 300);
    };

    plotElement.on('plotly_relayout', handleRelayout);
    return () => {
      plotElement.removeListener('plotly_relayout', handleRelayout);
      clearTimeout(layoutUpdateTimeout.current);
    };
  }, [props.envID, props.id, actualSelected, content]);

  // rendering
  // ---------

  const newPlot = () => {
    if (!content || !content.data) return;
    var data = content.data;

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
          if (smooth_d.marker?.line) smooth_d.marker.line.color = 0;

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
      content.data
        .filter((data) => data['type'] == 'scatter' && data['mode'] == 'lines')
        .map((d) => {
          d.opacity = 1.0;
        });

    // required for Plotly.react to register the update
    const layout = content.layout || (content.layout = {});
    content.layout.datarevision = props.version + '_' + actualSelected;

    // Adjust top margin and title position
    layout.margin = layout.margin || {};

    if (layout.title) {
      if (typeof layout.title === 'string') {
        layout.title = { text: layout.title };
      }
      if (layout.title.text) {
        layout.margin.t = 85;
      } else {
        layout.margin.t = 30;
      }
    } else {
      layout.margin.t = 30;
    }

    // draw / redraw plot with layout-options
    Plotly.react(contentID, data.concat(smooth_data), content.layout, {
      showLink: false,
      displaylogo: false,
      doubleClick: 'reset',
      doubleClickDelay: 500,
      modeBarButtonsToAdd: ['drawopenpath', 'eraseshape'],
    }).then(() => {
      const plotElement = plotlyRef.current;
      if (plotElement && plotElement._fullLayout && isDisplayed(plotElement)) {
        Plotly.Plots.resize(plotElement);
      }
    });
  };

  // check if data can be smoothed
  var contains_line_plots =
    content &&
    content.data &&
    content.data.some((data) => {
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

  var history_widget = '';
  if (isHistory && props.show_slider && props.content.length > 1) {
    history_widget = (
      <div className="widget" key="history_slider">
        <div style={{ display: 'flex' }}>
          <span>Frame:&nbsp;&nbsp;</span>
          <input
            type="range"
            min="0"
            max={props.content.length - 1}
            value={actualSelected}
            onChange={updateHistorySlider}
          />
          <span>
            &nbsp;&nbsp;
            {actualSelected}/{props.content.length - 1}
            &nbsp;&nbsp;
          </span>
        </div>
      </div>
    );
  }

  var caption_widget = '';
  if (isHistory && content && content.caption) {
    caption_widget = (
      <span className="widget" key="plot_caption">
        {content.caption}
      </span>
    );
  }

  return (
    <Pane
      {...props}
      handleDownload={handleDownload}
      handleMetadataExport={handleMetadataExport}
      barwidgets={[smooth_widget_button]}
      widgets={[history_widget, caption_widget, smooth_widget]}
      enablePropertyList
    >
      <div
        id={contentID}
        style={{ height: '100%', width: '100%' }}
        className={`plotly-graph-div${
          content.data?.[0]?.type === 'heatmap'
            ? ' plotly-heatmap'
            : content.data?.[0]?.type === 'contour'
              ? ' plotly-contour'
              : content.data?.[0]?.type === 'surface'
                ? ' plotly-surface'
                : ''
        }`}
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
