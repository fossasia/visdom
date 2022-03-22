/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';
var classNames = require('classnames');

class Pane extends React.Component {
  _windowRef = null;
  _barRef = null;

  close = () => {
    this.props.onClose(this.props.id);
  };

  focus = () => {
    this.props.onFocus(this.props.id);
  };

  download = () => {
    if (this.props.handleDownload) {
      this.props.handleDownload();
    }
  };

  reset = () => {
    if (this.props.handleReset) {
      this.props.handleReset();
    }
  };

  zoom = ev => {
    if (this.props.handleZoom) {
      this.props.handleZoom(ev);
    }
  };

  over = ev => {
    if (this.props.handleMouseMove) {
      this.props.handleMouseMove(ev);
    }
  };

  resize = () => {
    if (this.props.resize) {
      this.props.onResize();
    }
  };

  getWindowSize = () => {
    return {
      h: this._windowRef.clientHeight,
      w: this._windowRef.clientWidth,
    };
  };

  getContentSize = () => {
    return {
      h: this._windowRef.clientHeight - this._barRef.scrollHeight,
      w: this._windowRef.clientWidth,
    };
  };

  updateCompareViewSelection = value => {};

  shouldComponentUpdate(nextProps) {
    if (this.props.contentID !== nextProps.contentID) {
      return true;
    } else if (this.props.h !== nextProps.h || this.props.w !== nextProps.w) {
      return true;
    } else if (this.props.children !== nextProps.children) {
      return true;
    } else if (this.props.isFocused !== nextProps.isFocused) {
      return true;
    }

    return false;
  }

  render() {
    let widgets = [].concat(this.props.widgets);

    let windowClassNames = classNames({
      window: true,
      focus: this.props.isFocused,
    });

    let barClassNames = classNames({
      bar: true,
      focus: this.props.isFocused,
    });

    // compare view selection
    if (
      this.props.has_compare &&
      this.props.compare_content_info &&
      this.props.compare_view_mode != 'merge'
    ) {
      var select = this.props.compare_selection_i;
      widgets.push(
        <div key="compare_selection" className="widget compare_selection">
          <span>Selected Env</span>
          <select onChange={this.props.updateCompareViewSelection}>
            {this.props.compare_content_info.map((info, id) => (
              <option key={id} value={info.content_i}>
                {info.plot_name}
              </option>
            ))}
          </select>
        </div>
      );
    }

    return (
      <div
        className={windowClassNames}
        onClick={this.focus}
        onDoubleClick={this.reset}
        onWheel={this.zoom}
        onMouseMove={this.over}
        ref={ref => (this._windowRef = ref)}
      >
        <div className={barClassNames} ref={ref => (this._barRef = ref)}>
          <button title="close" onClick={this.close}>
            X
          </button>
          <button title="save" onClick={this.download}>
            &#8681;
          </button>
          <button
            title="reset"
            onClick={this.reset}
            hidden={!this.props.handleReset}
          >
            &#10226;
          </button>
          <div>{this.props.title}</div>
        </div>
        <div className="content">{this.props.children}</div>
        <div className="widgets">{widgets}</div>
      </div>
    );
  }
}

module.exports = Pane;
