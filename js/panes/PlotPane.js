/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */
//PlotPane.js
import React, { useEffect, useRef, useState } from 'react';
const { usePrevious } = require('../util');
import Pane from './Pane';
const { sgg } = require('ml-savitzky-golay-generalized');

var PlotPane = (props) => {
  const { contentID, content } = props;

  // state varibles
  // --------------
  const plotlyRef = useRef();
  const previousContent = usePrevious(content);
  const maxsmoothvalue = 100;
  const [smoothWidgetActive, setSmoothWidgetActive] = useState(false);
  const [smoothvalue, setSmoothValue] = useState(1);
  const [showExportHistory, setShowExportHistory] = useState(false);
  const [exportHistory, setExportHistory] = useState([]);

  const loadExportHistory = () => {
    try {
      return JSON.parse(localStorage.getItem('visdom_export_log') || '[]');
    } catch {
      return [];
    }
  };

  const refreshExportHistory = () => {
    setExportHistory(loadExportHistory().slice().reverse());
  };

  const resizePlot = () => {
    if (plotlyRef.current) {
      setTimeout(() => {
        Plotly.Plots.resize(plotlyRef.current);
      }, 0);
    }
  };

  // private events
  // -------------
  const toggleSmoothWidget = () => {
    setSmoothWidgetActive(!smoothWidgetActive);
  };
  const updateSmoothSlider = (value) => {
    setSmoothValue(value);
  };

  const saveExportLog = (entry) => {
    try {
      const existing = loadExportHistory();
      existing.push(entry);
      localStorage.setItem('visdom_export_log', JSON.stringify(existing));
    } catch (err) {
      console.error('Failed to save export log', err);
    }
  };

  const handleDownload = async (format = 'svg') => {
    const filename = `${contentID}_${new Date()
      .toISOString()
      .replace(/[:.]/g, '-')}`;
    const timestamp = new Date().toISOString();

    try {
      await Plotly.downloadImage(plotlyRef.current, {
        format,
        filename,
      });

      saveExportLog({
        contentID,
        filename,
        format,
        timestamp,
        title: content?.layout?.title || '',
        status: 'success',
      });
    } catch (error) {
      saveExportLog({
        contentID,
        filename,
        format,
        timestamp,
        title: content?.layout?.title || '',
        status: 'error',
        error: error?.message || String(error),
      });
    } finally {
      refreshExportHistory();
    }
  };

  // events
  // ------
  useEffect(() => {
    if (previousContent) {
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
    resizePlot();
  });

  useEffect(() => {
    if (showExportHistory) {
      refreshExportHistory();
    }
    resizePlot();
  }, [showExportHistory]);

  // rendering
  // ---------

  const newPlot = () => {
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
      content.data
        .filter((data) => data['type'] == 'scatter' && data['mode'] == 'lines')
        .map((d) => {
          d.opacity = 1.0;
        });

    // required for Plotly.react to register the update
    content.layout.datarevision = props.version;

    // draw / redraw plot with layout-options
    Plotly.react(contentID, data.concat(smooth_data), content.layout, {
      showLink: true,
      linkText: 'Edit',
      modeBarButtonsToRemove: ['toImage'],
    });
  };

  // check if data can be smoothed
  var contains_line_plots = content.data.some((data) => {
    return data['type'] == 'scatter' && data['mode'] == 'lines';
  });

  var smooth_widget_button = null;
  var smooth_widget = null;
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

  return (
    <Pane
      {...props}
      handleDownload={handleDownload}
      onShowExportHistory={() => setShowExportHistory((v) => !v)}
      barwidgets={[smooth_widget_button].filter(Boolean)}
      widgets={[
        smooth_widget,
        showExportHistory && (
          <div
            key="export_history"
            className="widget"
            style={{
              maxHeight: '200px',
              overflowY: 'auto',
              overflowX: 'hidden',
              padding: '6px',
            }}
          >
            <h4>Export history</h4>
            {exportHistory.length === 0 ? (
              <div>No export history yet.</div>
            ) : (
              exportHistory.map((item, idx) => (
                <div
                key={`${item.timestamp}-${item.format}`}
                  style={{
                    marginBottom: '10px',
                    borderBottom: '1px solid #eee',
                    paddingBottom: '6px',
                  }}
                >
                  <div style={{ fontWeight: 'bold' }}>
                    {item.format.toUpperCase()}
                  </div>

                  <div style={{ fontSize: '12px', color: '#555' }}>
                    {item.timestamp
                      ? new Date(item.timestamp).toLocaleString()
                      : ''}
                  </div>

                  <div
                    style={{
                      fontSize: '12px',
                      color: item.status === 'error' ? '#c00' : 'green',
                    }}
                  >
                    {item.status}
                  </div>

                  {item.error ? (
                    <div style={{ fontSize: '12px', color: '#c00' }}>
                      {item.error}
                    </div>
                  ) : null}
                </div>
              ))
            )}
          </div>
        ),
      ].filter(Boolean)}
      enablePropertyList
    >
      <div
        id={contentID}
        style={{
          height: showExportHistory ? '70%' : '100%',
          width: '100%',
        }}
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