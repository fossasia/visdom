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
    )
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
