/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const Pane = require('./Pane');

class PlotPane extends React.Component {
  _paneRef = null;
  _plotlyRef = null;
  _width = null;
  _height = null;

  componentDidMount() {
    this.newPlot();
  }

  componentDidUpdate(prevProps, prevState) {
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
    if (old_x.autorange === false && !new_range_set) {
      // Take the old x axis layout if changed
      this.props.content.layout.xaxis = old_x;
    }
    let old_y = prevProps.content.layout.yaxis;
    let new_y = this.props.content.layout.yaxis;
    new_range_set = new_y !== undefined && new_y.autorange === false;
    if (old_y.autorange === false && !new_range_set) {
      // Take the old y axis layout if changed
      this.props.content.layout.yaxis = old_y;
    }
    this.newPlot();
  }

  shouldComponentUpdate(nextProps, nextState) {
    if (this.props.contentID !== nextProps.contentID) {
      return true;
    }
    else if (this.props.h !== nextProps.h || this.props.w !== nextProps.w) {
      return true;
    }
    else if (this.props.isFocused !== nextProps.isFocused) {
      return true;
    }
    return false;
  }

  newPlot = () => {
    Plotly.newPlot(
      this.props.contentID,
      this.props.content.data,
      this.props.content.layout,
      {showLink: true, linkText: ' '}
    );
  }

  handleDownload = () => {
    Plotly.downloadImage(this._plotlyRef, {
      format: 'svg',
      filename: this.props.contentID,
    });
  }

  resize = () => {
    this.componentDidUpdate();
  }

  render() {
    return (
      <Pane
        {...this.props}
        handleDownload={this.handleDownload}
        ref={(ref) => this._paneRef = ref}>
        <div
          id={this.props.contentID}
          style={{height: '100%', width: '100%'}}
          className="plotly-graph-div"
          ref={(ref) => this._plotlyRef = ref}
        />
      </Pane>
    )
  }
}

module.exports = PlotPane;
