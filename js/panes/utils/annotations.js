/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';

const THREE_D_TYPES = ['scatter3d', 'surface', 'mesh3d'];

// the note box is sized and placed from custom properties in style.css, so
// the resolved value is what plotly stores and what an export re-renders
const cssCache = {};

// an empty read is not cached, so a value asked for before the stylesheet
// applied is picked up on the next call rather than remembered as missing
const cssValue = (name) => {
  if (!cssCache[name]) {
    cssCache[name] = getComputedStyle(document.documentElement)
      .getPropertyValue(name)
      .trim();
  }
  return cssCache[name];
};

const cssNumber = (name) => parseFloat(cssValue(name));

const fontSize = () => cssNumber('--annotation-font-size');
const arrowLength = () => cssNumber('--annotation-arrow-length');
const boxGap = () => cssNumber('--annotation-gap');
const widthRatio = () => cssNumber('--annotation-width-ratio');
const heightRatio = () => cssNumber('--annotation-height-ratio');
const crowdRatio = () => cssNumber('--annotation-crowd-ratio');
const charWidthRatio = () => cssNumber('--annotation-char-width-ratio');
const lineHeightRatio = () => cssNumber('--annotation-line-height-ratio');
const noteBackground = () => cssValue('--annotation-background');

// not templateitemname: plotly hides items whose template entry is missing
const PINNED = 'visdom_pinned';
const NOTE = 'visdom_note';
const isPinned = (a) => a[PINNED] === true;

// plotly draws a subset of html, so a note is escaped before it is rendered
const escapeNote = (note) =>
  note.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// reading an escaped note back, so editing one does not escape it a second time
const unescapeNote = (note) =>
  note.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// heatmap and contour points carry a z as well, so the trace type decides
const isThreeD = (trace) =>
  !!trace && (!!trace.scene || THREE_D_TYPES.includes(trace.type));

// a note takes its color from the trace it is pinned to
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

// how much text fits is a share of the pane, so a note scales with the window
const noteBounds = (plotElement) => ({
  perLine: Math.max(
    8,
    Math.floor(
      (plotElement.clientWidth * widthRatio()) / (fontSize() * charWidthRatio())
    )
  ),
  lines: Math.max(
    1,
    Math.floor(
      (plotElement.clientHeight * heightRatio()) /
        (fontSize() * lineHeightRatio())
    )
  ),
});

const chipHeight = (annotation) =>
  annotation.text.split('<br>').length * fontSize() * lineHeightRatio() +
  boxGap();

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
  return lines.length <= maxLines ? shown : shown + '…';
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
      (p) => span > 0 && Math.abs(p.x - a.x) < span * crowdRatio()
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
        -arrowLength()
      );
    }

    placed.push(next);
    return next;
  });
};

const readAnnotations = (plotElement) => plotElement.layout?.annotations || [];

// crowding is judged against the plot's own x range
const xSpan = (traces) => {
  let min = Infinity;
  let max = -Infinity;
  (traces || []).forEach((trace) => {
    (trace.x || []).forEach((v) => {
      if (typeof v !== 'number') return;
      if (v < min) min = v;
      if (v > max) max = v;
    });
  });
  return max > min ? max - min : 0;
};

// where the click landed inside the pane, so the editor opens next to it
const mouseOffset = (eventdata, plotElement) => {
  const rect = plotElement.getBoundingClientRect();
  const mouse = eventdata.event || {};
  return {
    left: (mouse.clientX || rect.left) - rect.left,
    top: (mouse.clientY || rect.top) - rect.top,
  };
};

const pendingFromPoint = (eventdata, point, plotElement) => ({
  x: point.x,
  y: point.y,
  name: point.fullData && point.fullData.name,
  color: traceColor(point),
  ...mouseOffset(eventdata, plotElement),
});

const pendingFromNote = (eventdata, note, plotElement) => ({
  x: note.x,
  y: note.y,
  name: note.name,
  color: note.font && note.font.color,
  index: eventdata.index,
  ...mouseOffset(eventdata, plotElement),
});

// a drag reports annotations[i].ax, our own writes a bare annotations
const draggedIndexes = (eventdata) =>
  Object.keys(eventdata)
    .map((k) => k.match(/^annotations\[(\d+)]\./))
    .filter(Boolean)
    .map((match) => Number(match[1]));

const pinDragged = (annotations, dragged) => {
  const current = annotations || [];
  dragged.forEach((i) => {
    if (current[i] && current[i].hovertext) current[i][PINNED] = true;
  });
  return current;
};

const buildAnnotation = (pendingPoint, noteText, plotElement, previous) => {
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
    font: { size: fontSize(), color: pendingPoint.color },
    bgcolor: noteBackground(),
    bordercolor: pendingPoint.color,
    borderwidth: 1,
    borderpad: 3,
  };

  // restack positions everything, except boxes already dragged by hand
  if (previous && isPinned(previous)) {
    Object.assign(annotation, {
      [PINNED]: true,
      ax: previous.ax,
      ay: previous.ay,
    });
  }

  return annotation;
};

const withAnnotation = (current, annotation, index) =>
  index === undefined
    ? current.concat(annotation)
    : current.map((a, i) => (i === index ? annotation : a));

// keep the editor inside the pane so its buttons are never cut off
const clampEditor = (editor, pendingPoint) => {
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
};

// Owns the note state for one plot pane and hands back the pieces it renders:
// the marker button, the hint bar and the floating editor.
const useAnnotations = ({
  plotlyRef,
  content,
  envID,
  paneID,
  frame,
  sendPlotLayoutUpdate,
  readonly,
}) => {
  const [active, setActive] = useState(false);
  const [pendingPoint, setPendingPoint] = useState(null);
  const [noteText, setNoteText] = useState('');
  const inputRef = useRef(null);
  const editorRef = useRef(null);

  // notes are anchored in 2d data coordinates
  const enabled =
    !!content && !!content.data && !content.data.some(isThreeD) && !readonly;

  // an open note points into the frame it was opened on
  useEffect(() => {
    setPendingPoint(null);
    setNoteText('');
  }, [frame]);

  useEffect(() => {
    if (pendingPoint && inputRef.current) inputRef.current.focus();
  }, [pendingPoint]);

  useLayoutEffect(() => {
    clampEditor(editorRef.current, pendingPoint);
  }, [pendingPoint, noteText]);

  const applyAnnotations = (annotations) => {
    const positioned = restack(annotations, xSpan(content && content.data));
    Plotly.relayout(plotlyRef.current, { annotations: positioned });

    if (content && content.layout) {
      content.layout.annotations = positioned;
    }

    sendPlotLayoutUpdate(envID, paneID, { annotations: positioned }, frame);
  };

  const addAnnotation = () => {
    const plotElement = plotlyRef.current;
    if (!plotElement || !pendingPoint || !noteText.trim()) return;

    const current = readAnnotations(plotElement);
    const annotation = buildAnnotation(
      pendingPoint,
      noteText,
      plotElement,
      current[pendingPoint.index]
    );

    applyAnnotations(withAnnotation(current, annotation, pendingPoint.index));

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

  useEffect(() => {
    const plotElement = plotlyRef.current;
    if (!plotElement || !active) return;

    const handleClick = (eventdata) => {
      const point = eventdata.points && eventdata.points[0];
      // the button is hidden on 3d panes, but a mixed pane can still fire
      if (!point || isThreeD(point.fullData)) return;

      setPendingPoint(pendingFromPoint(eventdata, point, plotElement));
      setNoteText('');
    };

    // confusion_matrix labels its cells here too, and those have no hovertext
    const handleAnnotationClick = (eventdata) => {
      const clicked = readAnnotations(plotElement)[eventdata.index];
      if (!clicked || !clicked.hovertext) return;

      setPendingPoint(pendingFromNote(eventdata, clicked, plotElement));
      setNoteText(clicked[NOTE] ?? unescapeNote(clicked.hovertext));
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
  }, [active, envID, paneID, frame, content]);

  // path data from lucide-react's pencil-line icon (24x24 viewBox)
  const modebarButton = enabled
    ? {
        name: 'annotate',
        title: active ? 'stop annotating' : 'annotate points',
        icon: {
          width: 24,
          height: 24,
          path: 'M13 21h8 m15 5 4 4 M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z',
        },
        toggle: true,
        click: () => {
          setActive((wasActive) => !wasActive);
          setPendingPoint(null);
        },
      }
    : null;

  const hint =
    active && !pendingPoint ? (
      <div className="widget" key="annotate_widget">
        Annotating: click a point to add a note, click a note to edit it
      </div>
    ) : (
      ''
    );

  const editor =
    active && pendingPoint ? (
      <div
        className="annotate-editor"
        key="annotate_editor"
        ref={editorRef}
        style={{ left: pendingPoint.left, top: pendingPoint.top }}
      >
        <input
          type="text"
          ref={inputRef}
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
    ) : (
      ''
    );

  return { modebarButton, hint, editor };
};

export { draggedIndexes, pinDragged, useAnnotations };
