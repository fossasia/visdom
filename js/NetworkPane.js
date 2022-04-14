import React from 'react';
import Pane from './Pane';

class NetworkPane extends React.Component {
  _paneRef = null;
  _networkRef = null;
  _width = null;
  _height = null;

  handleDownload = () => {
    var link = document.createElement('a');
    link.download = `${this.props.title || 'visdom_network'}.jpg`;
    link.href = this.props.content.src;
    link.click();
  };

  CreateNetwork = (graph) => {
    var width = this.props._width,
      height = this.props._height;
    var color = d3.scale.category10();
    var force = d3.layout
      .force()
      .charge(-120)
      .linkDistance(120)
      .size([width, height]);
    var svg = d3
      .select('.Network_Div')
      .select('svg')
      .attr('viewBox', '0 0 ' + width + ' ' + height)
      .attr('preserveAspectRatio', 'xMinYMin meet')
      .classed('.svg-content', true);
    if (svg.empty()) {
      svg = d3
        .select('.Network_Div')
        .append('svg')
        .attr('viewBox', '0 0 ' + width + ' ' + height)
        .attr('preserveAspectRatio', 'xMinYMin meet');
    }

    if (this.props.directed) {
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
    if (this.props.showEdgeLabels) {
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
    if (this.props.showVertexLabels) {
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

  handleDownload = () => {
    saveSvgAsPng(document.getElementsByTagName('svg')[0], 'plot.png', {
      scale: 2,
      backgroundColor: '#FFFFFF',
    });
  };

  componentDidMount() {
    this.CreateNetwork(this.props.content);
  }

  render() {
    return (
      <Pane
        {...this.props}
        handleDownload={this.handleDownload}
        ref={(ref) => (this._paneRef = ref)}
      >
        <div
          id="Network_Div"
          style={{ height: '100%', width: '100%', flex: 1 }}
          className="Network_Div"
          ref={(ref) => (this._networkRef = ref)}
        />
      </Pane>
    );
  }
}

export default NetworkPane;
