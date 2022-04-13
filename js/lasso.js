/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import * as d3 from 'd3-selection';
import { dispatch as d3dispatch } from 'd3-dispatch';
import { drag as d3drag } from 'd3-drag';

function polygonToPath(polygon) {
  return (
    'M' +
    polygon
      .map(function (d) {
        return d.join(',');
      })
      .join('L')
  );
}

function distance(pt1, pt2) {
  return Math.sqrt(Math.pow(pt2[0] - pt1[0], 2) + Math.pow(pt2[1] - pt1[1], 2));
}

export default function lasso() {
  var dispatch = d3dispatch('start', 'end');

  // distance last point has to be to first point before
  // it auto closes when mouse is released
  var closeDistance = 75;

  function lasso(root) {
    // append a <g> with a rect
    var g = root.append('g').attr('class', 'lasso-group');
    var bbox = root.node().getBoundingClientRect();
    var area = g
      .append('rect')
      .attr('width', bbox.width)
      .attr('height', bbox.height)
      .attr('fill', 'tomato')
      .attr('opacity', 0);

    var drag = d3drag()
      .on('start', handleDragStart)
      .on('drag', handleDrag)
      .on('end', handleDragEnd);

    area.call(drag);

    var lassoPolygon;
    var lassoPath;
    var closePath;

    function handleDragStart() {
      lassoPolygon = [d3.mouse(this)];
      if (lassoPath) {
        lassoPath.remove();
      }

      lassoPath = g
        .append('path')
        .attr('fill', '#0bb')
        .attr('fill-opacity', 0.2)
        .attr('stroke', '#0bb')
        .attr('stroke-width', '3px')
        .attr('stroke-dasharray', '7, 4');

      closePath = g
        .append('line')
        .attr('x2', lassoPolygon[0][0])
        .attr('y2', lassoPolygon[0][1])
        .attr('stroke', '#0bb')
        .attr('stroke-width', '3px')
        .attr('stroke-dasharray', '7, 4')
        .attr('opacity', 0);

      dispatch.call('start', lasso, lassoPolygon);
    }

    function handleDrag() {
      var point = d3.mouse(this);
      lassoPolygon.push(point);
      lassoPath.attr('d', polygonToPath(lassoPolygon));

      // indicate if we are within closing distance
      if (
        distance(lassoPolygon[0], lassoPolygon[lassoPolygon.length - 1]) <
        closeDistance
      ) {
        closePath.attr('x1', point[0]).attr('y1', point[1]).attr('opacity', 1);
      } else {
        closePath.attr('opacity', 0);
      }
    }

    function handleDragEnd() {
      // remove the close path
      closePath.remove();
      closePath = null;

      // successfully closed
      if (
        distance(lassoPolygon[0], lassoPolygon[lassoPolygon.length - 1]) <
        closeDistance
      ) {
        lassoPath.attr('d', polygonToPath(lassoPolygon) + 'Z');
        dispatch.call('end', lasso, lassoPolygon);

        // otherwise cancel
      } else {
        lassoPath.remove();
        lassoPath = null;
        lassoPolygon = null;
      }
    }

    lasso.reset = function () {
      if (lassoPath) {
        lassoPath.remove();
        lassoPath = null;
      }

      lassoPolygon = null;
      if (closePath) {
        closePath.remove();
        closePath = null;
      }
    };
  }

  lasso.on = function (type, callback) {
    dispatch.on(type, callback);
    return lasso;
  };

  return lasso;
}
