/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, {
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
const { usePrevious } = require('../util');
import ApiContext from '../api/ApiContext';
import Pane from './Pane';
import { typesetMathJax } from './utils/mathjaxHelpers';
const { sgg } = require('ml-savitzky-golay-generalized');

const ANNOTATION_FONT_SIZE = 11;
const ANNOTATION_ARROW_LEN = 30;
const ANNOTATION_GAP = 6;
const ANNOTATION_WIDTH_RATIO = 0.25;
const ANNOTATION_HEIGHT_RATIO = 0.2;
const ANNOTATION_CROWD_RATIO = 0.08;
const CHAR_WIDTH_RATIO = 0.6;
const LINE_HEIGHT_RATIO = 1.3;
const THREE_D_TYPES = ['scatter3d', 'surface', 'mesh3d'];

// not templateitemname: plotly hides items whose template entry is missing
const PINNED = 'visdom_pinned';
const NOTE = 'visdom_note';
const isPinned = (a) => a[PINNED] === true;

// plotly draws a subset of html, so a note is escaped before it is rendered
const escapeNote = (note) =>
  note.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// heatmap and contour points carry a z as well, so the trace type decides
const isThreeD = (trace) =>
  !!trace && (!!trace.scene || THREE_D_TYPES.includes(trace.type));

const noteBounds = (plotElement) => ({
  perLine: Math.max(
    8,
    Math.floor(
      (plotElement.clientWidth * ANNOTATION_WIDTH_RATIO) /
        (ANNOTATION_FONT_SIZE * CHAR_WIDTH_RATIO)
    )
  ),
  lines: Math.max(
    1,
    Math.floor(
      (plotElement.clientHeight * ANNOTATION_HEIGHT_RATIO) /
        (ANNOTATION_FONT_SIZE * LINE_HEIGHT_RATIO)
    )
  ),
});

const chipHeight = (annotation) =>
  annotation.text.split('<br>').length *
    ANNOTATION_FONT_SIZE *
    LINE_HEIGHT_RATIO +
  ANNOTATION_GAP;

// <br> is a line break in plotly annotation text
const wrapNote = (note, perLine, maxLines) => {
  const words = [];
  note
    .trim()
    .split(/\s+/)
    .forEach((word) => {
      for (let i = 0; i < word.length; i += perLine) {
        words.push(word.slice(i, i + perLine));
      }
    });

  const lines = [];
  words.forEach((word) => {
    const last = lines.length - 1;
    if (last >= 0 && (lines[last] + ' ' + word).length <= perLine) {
      lines[last] += ' ' + word;
    } else {
      lines.push(word);
    }
  });

  const shown = lines.slice(0, maxLines).map(escapeNote).join('<br>');
  return lines.length <= maxLines ? shown : shown + '\u2026';
};

// boxes on one point stack above it, nearby ones clear what is already
// there, and a delete closes the gap. dragged boxes keep where they were put
const restack = (annotations, span) => {
  const placed = [];

  return annotations.map((a) => {
    if (!a.hovertext) return a;

    const dragged = isPinned(a);
    const auto = placed.filter((p) => !isPinned(p));
    const onPoint = auto.filter((p) => p.x === a.x && p.y === a.y);
    const nearby = auto.filter(
      (p) => span > 0 && Math.abs(p.x - a.x) < span * ANNOTATION_CROWD_RATIO
    );

    const next = {
      ...a,
      showarrow: true,
      // only a box stacked over another aimed at the same spot hides its arrow
      arrowcolor:
        !dragged && onPoint.length ? 'rgba(0,0,0,0)' : a.font && a.font.color,
    };

    if (!dragged) {
      next.ax = 0;
      next.ay = (onPoint.length ? onPoint : nearby).reduce(
        (top, p) => Math.min(top, p.ay - chipHeight(p)),
        -ANNOTATION_ARROW_LEN
      );
    }

    placed.push(next);
    return next;
  });
};

var PlotPane = (props) => {
  const { contentID, type, selected } = props;
  const isHistory = type === 'plot_history';

  // state variables
  // --------------
  const plotlyRef = useRef();
  const captionRef = useRef();
  const maxsmoothvalue = 100;
  const [smoothWidgetActive, setSmoothWidgetActive] = useState(false);
  const [smoothvalue, setSmoothValue] = useState(1);
  const [annotateActive, setAnnotateActive] = useState(false);
  const [pendingPoint, setPendingPoint] = useState(null);
  const [noteText, setNoteText] = useState('');
  const noteInputRef = useRef(null);
  const editorRef = useRef(null);
  const [actualSelected, setActualSelected] = useState(
    isHistory ? selected || 0 : 0
  );
  const { sendPlotLayoutUpdate, sessionInfo } = useContext(ApiContext);
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

  // an open note points into the frame it was opened on
  useEffect(() => {
    setPendingPoint(null);
    setNoteText('');
  }, [actualSelected]);

  useEffect(() => {
    let cancelled = false;
    typesetMathJax(captionRef.current, () => cancelled);
    return () => {
      cancelled = true;
    };
  }, [content && content.caption]);

  // private events
  // -------------
  const toggleSmoothWidget = () => {
    setSmoothWidgetActive(!smoothWidgetActive);
  };
  const updateSmoothSlider = (value) => {
    setSmoothValue(value);
  };
  const toggleAnnotateWidget = () => {
    setAnnotateActive(!annotateActive);
    setPendingPoint(null);
  };

  const traceColor = (point) => {
    const trace = point.fullData || point.data || {};
    const lineColor = trace.line && trace.line.color;
    if (typeof lineColor === 'string') return lineColor;
    const markerColor = trace.marker && trace.marker.color;
    if (typeof markerColor === 'string') return markerColor;
    if (Array.isArray(markerColor)) {
      const pointColor = markerColor[point.pointIndex];
      if (typeof pointColor === 'string') return pointColor;
    }
    return undefined;
  };

  const applyAnnotations = (annotations) => {
    const positioned = restack(annotations, xSpan());
    Plotly.relayout(plotlyRef.current, { annotations: positioned });

    if (content && content.layout) {
      content.layout.annotations = positioned;
    }

    sendPlotLayoutUpdate(
      props.envID,
      props.id,
      { annotations: positioned },
      isHistory ? actualSelected : undefined
    );
  };

  const xSpan = () => {
    let min = Infinity;
    let max = -Infinity;
    ((content && content.data) || []).forEach((trace) => {
      (trace.x || []).forEach((v) => {
        if (typeof v !== 'number') return;
        if (v < min) min = v;
        if (v > max) max = v;
      });
    });
    return max > min ? max - min : 0;
  };

  const readAnnotations = (plotElement) =>
    plotElement.layout?.annotations || [];

  useEffect(() => {
    if (pendingPoint && noteInputRef.current) noteInputRef.current.focus();
  }, [pendingPoint]);

  useLayoutEffect(() => {
    const editor = editorRef.current;
    const bounds = editor && editor.offsetParent;
    if (!editor || !bounds || !pendingPoint) return;

    const left = Math.min(
      pendingPoint.left,
      bounds.clientWidth - editor.offsetWidth
    );
    const top = Math.min(
      pendingPoint.top,
      bounds.clientHeight - editor.offsetHeight
    );

    editor.style.left = Math.max(0, left) + 'px';
    editor.style.top = Math.max(0, top) + 'px';
  }, [pendingPoint, noteText]);

  const addAnnotation = () => {
    const plotElement = plotlyRef.current;
    if (!plotElement || !pendingPoint || !noteText.trim()) return;

    const bounds = noteBounds(plotElement);
    const annotation = {
      x: pendingPoint.x,
      y: pendingPoint.y,
      xref: 'x',
      yref: 'y',
      text: wrapNote(noteText, bounds.perLine, bounds.lines),
      align: 'left',
      hovertext: escapeNote(noteText.trim()),
      [NOTE]: noteText.trim(),
      name: pendingPoint.name,
      arrowhead: 2,
      arrowsize: 1,
      arrowwidth: 1.5,
      captureevents: true,
      font: { size: ANNOTATION_FONT_SIZE, color: pendingPoint.color },
      bgcolor: '#fff',
      bordercolor: pendingPoint.color,
      borderwidth: 1,
      borderpad: 3,
    };

    // restack positions everything, except boxes already dragged by hand
    const current = readAnnotations(plotElement);
    const previous = current[pendingPoint.index];

    if (previous && isPinned(previous)) {
      Object.assign(annotation, {
        [PINNED]: true,
        ax: previous.ax,
        ay: previous.ay,
      });
    }

    applyAnnotations(
      pendingPoint.index === undefined
        ? current.concat(annotation)
        : current.map((a, i) => (i === pendingPoint.index ? annotation : a))
    );

    setPendingPoint(null);
    setNoteText('');
  };

  const deleteAnnotation = () => {
    const plotElement = plotlyRef.current;
    if (!plotElement || !pendingPoint || pendingPoint.index === undefined) {
      return;
    }

    applyAnnotations(
      readAnnotations(plotElement).filter((_, i) => i !== pendingPoint.index)
    );

    setPendingPoint(null);
    setNoteText('');
  };

  const dpiToScale = (dpi) => (dpi ? dpi / 96 : 1);

  const handleExport = (format, dpi) => {
    Plotly.downloadImage(plotlyRef.current, {
      format: format === 'jpg' ? 'jpeg' : format,
      scale: dpiToScale(dpi),
      filename: contentID || 'plot',
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
    link.download = `${contentID || 'plot'}_metadata.json`;
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
      const keys = Object.keys(eventdata);
      const touchedShapes = keys.some((k) => k.includes('shapes'));
      // a drag reports annotations[i].ax, our own writes a bare annotations
      const dragged = keys
        .map((k) => k.match(/^annotations\[(\d+)]\./))
        .filter(Boolean)
        .map((match) => Number(match[1]));
      if (!touchedShapes && !dragged.length) return;

      clearTimeout(layoutUpdateTimeout.current);
      layoutUpdateTimeout.current = setTimeout(() => {
        const shapes = plotElement.layout?.shapes || [];
        const annotations = plotElement.layout?.annotations || [];

        dragged.forEach((i) => {
          if (annotations[i]) annotations[i][PINNED] = true;
        });

        if (content && content.layout) {
          content.layout.shapes = shapes;
          content.layout.annotations = annotations;
        }

        sendPlotLayoutUpdate(
          props.envID,
          props.id,
          { shapes, annotations },
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

  useEffect(() => {
    const plotElement = plotlyRef.current;
    if (!plotElement || !annotateActive) return;

    const handleClick = (eventdata) => {
      const point = eventdata.points && eventdata.points[0];
      // the button is hidden on 3d panes, but a mixed pane can still fire
      if (!point || isThreeD(point.fullData)) return;

      const rect = plotElement.getBoundingClientRect();
      const mouse = eventdata.event || {};

      setPendingPoint({
        x: point.x,
        y: point.y,
        name: point.fullData && point.fullData.name,
        color: traceColor(point),
        left: (mouse.clientX || rect.left) - rect.left,
        top: (mouse.clientY || rect.top) - rect.top,
      });
      setNoteText('');
    };

    // confusion_matrix labels its cells here too, and those have no hovertext
    const handleAnnotationClick = (eventdata) => {
      const clicked = readAnnotations(plotElement)[eventdata.index];
      if (!clicked || !clicked.hovertext) return;

      const rect = plotElement.getBoundingClientRect();
      const mouse = eventdata.event || {};

      setPendingPoint({
        x: clicked.x,
        y: clicked.y,
        name: clicked.name,
        color: clicked.font && clicked.font.color,
        index: eventdata.index,
        left: (mouse.clientX || rect.left) - rect.left,
        top: (mouse.clientY || rect.top) - rect.top,
      });
      setNoteText(clicked[NOTE] ?? clicked.hovertext);
    };

    plotElement.on('plotly_click', handleClick);
    plotElement.on('plotly_clickannotation', handleAnnotationClick);
    return () => {
      plotElement.removeListener('plotly_click', handleClick);
      plotElement.removeListener(
        'plotly_clickannotation',
        handleAnnotationClick
      );
    };
  }, [annotateActive, props.envID, props.id, actualSelected, content]);

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
          if (windowSize < 5 || !smooth_d.x || smooth_d.x.length <= 5) {
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

    if (content.caption) {
      layout.margin.b = Math.max(layout.margin.b || 60, 100);
    }

    // draw / redraw plot with layout-options
    Plotly.react(contentID, data.concat(smooth_data), content.layout, {
      showLink: false,
      displaylogo: false,
      doubleClick: 'reset',
      doubleClickDelay: 500,
      modeBarButtonsToAdd: ['drawopenpath', 'eraseshape'],
      // dragging a note box leaves its arrow on the data point
      edits: { annotationTail: !sessionInfo?.readonly },
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

  // notes are anchored in 2d data coordinates
  var annotate_widget_button = '';
  if (
    content &&
    content.data &&
    !content.data.some(isThreeD) &&
    !sessionInfo?.readonly
  ) {
    annotate_widget_button = (
      <button
        key="annotate_widget_button"
        title="annotate points"
        onClick={toggleAnnotateWidget}
        className={annotateActive ? 'pull-right active' : 'pull-right'}
      >
        <span className="glyphicon glyphicon-pencil" />
      </button>
    );
  }

  var annotate_widget = '';
  if (annotateActive && !pendingPoint) {
    annotate_widget = (
      <div className="widget" key="annotate_widget">
        Annotating: click a point to add a note, click a note to edit it
      </div>
    );
  }

  var annotate_editor = '';
  if (annotateActive && pendingPoint) {
    annotate_editor = (
      <div
        className="annotate-editor"
        key="annotate_editor"
        ref={editorRef}
        style={{ left: pendingPoint.left, top: pendingPoint.top }}
      >
        <input
          type="text"
          ref={noteInputRef}
          placeholder={
            pendingPoint.name
              ? 'note for ' + pendingPoint.name
              : 'note for this point'
          }
          value={noteText}
          onChange={(ev) => setNoteText(ev.target.value)}
          onKeyDown={(ev) => {
            if (ev.key === 'Enter') addAnnotation();
            else if (ev.key === 'Escape') setPendingPoint(null);
          }}
        />
        <button onClick={addAnnotation} disabled={!noteText.trim()}>
          {pendingPoint.index === undefined ? 'add' : 'save'}
        </button>
        {pendingPoint.index !== undefined && (
          <button onClick={deleteAnnotation}>delete</button>
        )}
        <button onClick={() => setPendingPoint(null)}>cancel</button>
      </div>
    );
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
  if (content && content.caption) {
    caption_widget = (
      <div className="widget plot-caption" key="plot_caption" ref={captionRef}>
        {content.caption}
      </div>
    );
  }

  return (
    <Pane
      {...props}
      handleExport={handleExport}
      handleMetadataExport={handleMetadataExport}
      barwidgets={[smooth_widget_button, annotate_widget_button]}
      widgets={[history_widget, caption_widget, smooth_widget, annotate_widget]}
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
      {annotate_editor}
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
