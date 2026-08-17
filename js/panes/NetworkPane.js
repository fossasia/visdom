/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

// ignoring errors due to statically loaded d3 and saveSvgAsPng
/* eslint-disable no-undef */

import React, { useEffect, useRef, useState } from 'react';

import { showToast } from '../toasts/toastEvents';
import Pane from './Pane';
import {
  downloadJpegWithDpi,
  downloadPngWithDpi,
} from './utils/Embeddpimetadata';
import { copyLatexToClipboard } from './utils/LatexExport';
import { downloadImageAsPdf } from './utils/pdfExport';

function NetworkPane(props) {
  const {
    content,
    directed,
    showEdgeLabels,
    showVertexLabels,
    _width,
    _height,
  } = props;

  const containerRef = useRef(null);
  const timeoutRef = useRef(null);
  const forceRef = useRef(null);
  const [downloadError, setDownloadError] = useState(null);

  // private events
  // --------------

  // NetworkPane always capture at 2x resolution by default (a
  // legacy behavior predating the DPI dropdown), unlike PlotPane/
  // EmbeddingsPane whose no-dpi-given default is a true native 1x. This
  // constant is the single source of truth for that: both the capture
  // scale AND the embedded DPI tag are derived from it, so they can't
  // silently drift apart from each other.

  const NETWORKPANE_LEGACY_SCALE = 2;

  const handleExport = (format, dpi) => {
    const svg = containerRef.current?.querySelector('svg');

    if (!svg) {
      setDownloadError('Graph is not ready yet. Please try again.');
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = setTimeout(() => {
        setDownloadError(null);
      }, 3000);
      return;
    }

    const filename = `${props.contentID || 'plot'}.${format}`;

    const scale = dpi ? dpi / 96 : NETWORKPANE_LEGACY_SCALE;

    requestAnimationFrame(() => {
      if (format === 'svg') {
        const clone = svg.cloneNode(true);
        inlineComputedStyles(svg, clone);
        const source = new XMLSerializer().serializeToString(clone);
        const blob = new Blob([source], {
          type: 'image/svg+xml;charset=utf-8',
        });
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => window.URL.revokeObjectURL(url), 1000);
        return;
      }

      if (format === 'pdf') {
        const PDF_CAPTURE_DPI = 300;
        const pdfScale = PDF_CAPTURE_DPI / 96;
        svgAsPngUri(
          svg,
          {
            scale: pdfScale,
            backgroundColor: '#FFFFFF',
            encoderType: 'image/jpeg',
            encoderOptions: 0.92,
          },
          (uri) => {
            downloadImageAsPdf(uri, filename, PDF_CAPTURE_DPI);
          }
        );
        return;
      }

      const dpiToEmbed = dpi || 96 * NETWORKPANE_LEGACY_SCALE;
      svgAsPngUri(
        svg,
        {
          scale,
          backgroundColor: '#FFFFFF',
          encoderType: format === 'jpg' ? 'image/jpeg' : 'image/png',
          encoderOptions: format === 'jpg' ? 0.92 : undefined,
        },
        (uri) => {
          if (format === 'jpg') {
            downloadJpegWithDpi(uri, filename, dpiToEmbed);
          } else {
            downloadPngWithDpi(uri, filename, dpiToEmbed);
          }
        }
      );
    });
  };

  const handleLatexExport = (style) => {
    copyLatexToClipboard(style, {
      contentID: props.contentID,
      id: props.id,
      caption: props.title,
      ext: 'pdf',
    })
      .then(() =>
        showToast('Copied!', 'success', {
          position: 'bottom-center',
          shape: 'pill',
          duration: 1500,
        })
      )
      .catch((err) => {
        console.error('NetworkPane LaTeX export failed:', err);
        showToast('Failed to Copy', 'error', {
          position: 'bottom-center',
          shape: 'pill',
          duration: 1500,
        });
      });
  };

  const SVG_STYLE_PROPS = [
    'fill',
    'stroke',
    'stroke-width',
    'stroke-opacity',
    'fill-opacity',
    'opacity',
    'font-family',
    'font-size',
  ];
  const inlineComputedStyles = (liveEl, cloneEl) => {
    const computed = window.getComputedStyle(liveEl);
    const styleStr = SVG_STYLE_PROPS.map(
      (prop) => `${prop}:${computed.getPropertyValue(prop)}`
    ).join(';');
    cloneEl.setAttribute('style', styleStr);

    for (let i = 0; i < liveEl.children.length; i++) {
      inlineComputedStyles(liveEl.children[i], cloneEl.children[i]);
    }
  };

  // effects
  // -------

  // initialize d3
  useEffect(() => {
    // stop the previous simulation's timer before starting a new one
    if (forceRef.current) {
      forceRef.current.stop();
    }
    d3.select(containerRef.current).selectAll('*').remove();
    CreateNetwork(content);

    return () => {
      if (forceRef.current) {
        forceRef.current.stop();
        forceRef.current = null;
      }
    };
  }, [content, directed, showEdgeLabels, showVertexLabels]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const CreateNetwork = (graph) => {
    var width = _width,
      height = _height;
    var color = d3.scale.category10();
    var force = d3.layout
      .force()
      .charge(-120)
      .linkDistance(120)
      .size([width, height]);
    forceRef.current = force;
    var svg = d3
      .select(containerRef.current)
      .select('svg')
      .attr('viewBox', '0 0 ' + width + ' ' + height)
      .attr('preserveAspectRatio', 'xMinYMin meet')
      .classed('svg-content', true);
    if (svg.empty()) {
      svg = d3
        .select(containerRef.current)
        .append('svg')
        .attr('viewBox', '0 0 ' + width + ' ' + height)
        .attr('preserveAspectRatio', 'xMinYMin meet')
        .classed('svg-content', true);
    }

    if (directed) {
      svg
        .append('defs')
        .append('marker')
        .attrs({
          id: 'arrowhead',
          viewBox: '-0 -5 10 10',
          refX: 13,
          refY: 0,
          orient: 'auto',
          markerWidth: 13,
          markerHeight: 13,
          xoverflow: 'visible',
        })
        .append('svg:path')
        .attr('d', 'M 0,-5 L 10 ,0 L 0,5')
        .attr('fill', '#999')
        .style('stroke', 'none');
    }

    force.nodes(graph.nodes).links(graph.edges).start();

    var link = svg
      .selectAll('.link')
      .data(graph.edges)
      .enter()
      .append('line')
      .attr('class', 'link')
      .attr('marker-end', 'url(#arrowhead)');

    link.append('title').text(function (d) {
      return d.type;
    });

    var edgepaths = svg
      .selectAll('.edgepath')
      .data(graph.edges)
      .enter()
      .append('path')
      .attrs({
        class: 'edgepath',
        'fill-opacity': 0,
        'stroke-opacity': 0,
        id: function (d, i) {
          return 'edgepath' + i;
        },
      })
      .style('pointer-events', 'none');

    var edgelabels = svg
      .selectAll('.edgelabel')
      .data(graph.edges)
      .enter()
      .append('text')
      .style('pointer-events', 'none')
      .attrs({
        class: 'edgelabel',
        id: function (d, i) {
          return 'edgelabel' + i;
        },
        'font-size': 10,
        fill: '#aaa',
      });
    if (showEdgeLabels) {
      edgelabels
        .append('textPath')
        .attr('xlink:href', (d, i) => '#edgepath' + i)
        .style('text-anchor', 'middle')
        .style('pointer-events', 'none')
        .attr('startOffset', '50%')
        .text((d) => d.label);
    }

    var node = svg
      .selectAll('.node')
      .data(graph.nodes)
      .enter()
      .append('g')
      .attr('class', 'node')
      .attr('r', 10) // radius
      .style('fill', function (d) {
        return color(d.club);
      })
      .call(force.drag);

    node.append('circle').attr('r', 10);

    node.append('title').text((d) => d.name);
    if (showVertexLabels) {
      node
        .append('text')
        .attr('dx', 12)
        .attr('dy', '.35em')
        .text((d) => d.label);
    }

    force.on('tick', function () {
      link
        .attr('x1', function (d) {
          return d.source.x;
        })
        .attr('y1', function (d) {
          return d.source.y;
        })
        .attr('x2', function (d) {
          return d.target.x;
        })
        .attr('y2', function (d) {
          return d.target.y;
        });

      node.attr('transform', function (d) {
        return 'translate(' + d.x + ',' + d.y + ')';
      });

      edgepaths.attr('d', function (d) {
        return (
          'M ' +
          d.source.x +
          ' ' +
          d.source.y +
          ' L ' +
          d.target.x +
          ' ' +
          d.target.y
        );
      });

      edgelabels.attr('transform', function (d) {
        if (d.target.x < d.source.x) {
          var bbox = this.getBBox();

          var rx = bbox.x + bbox.width / 2;
          var ry = bbox.y + bbox.height / 2;
          return 'rotate(180 ' + rx + ' ' + ry + ')';
        } else {
          return 'rotate(0)';
        }
      });
    });
  };

  // rendering
  // ---------

  return (
    <Pane
      {...props}
      handleExport={handleExport}
      handleLatexExport={handleLatexExport}
    >
      {downloadError && <div className="error-message">{downloadError}</div>}
      <div
        ref={containerRef}
        style={{ height: '100%', width: '100%', flex: 1 }}
        className="Network_Div"
      />
    </Pane>
  );
}

export default NetworkPane;
