/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

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

export {
  escapeNote,
  fontSize,
  isPinned,
  isThreeD,
  NOTE,
  noteBackground,
  noteBounds,
  PINNED,
  restack,
  traceColor,
  wrapNote,
};
