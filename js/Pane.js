/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

 class Pane extends React.Component {
  _windowRef: null;
  _barRef: null;

  close = () => {
    this.props.onClose(this.props.id);
  }

  focus = () => {
    this.props.onFocus(this.props.id);
  }

  download = () => {
    if (this.props.handleDownload) {
      this.props.handleDownload();
    }
  }

  resize = () => {
    if (this.props.resize) {
      this.props.onResize();
    }
  }

  getWindowSize = () => {
    return {
      h: this._windowRef.clientHeight,
      w: this._windowRef.clientWidth,
    };
  }

  getContentSize = () => {
    return {
      h: this._windowRef.clientHeight - this._barRef.scrollHeight,
      w: this._windowRef.clientWidth,
    };
  }

  shouldComponentUpdate(nextProps, nextState) {
    if (this.props.contentID !== nextProps.contentID){
      return true;
    }
    else if (this.props.h !== nextProps.h || this.props.w !== nextProps.w) {
      return true;
    }
    else if (this.props.children !== nextProps.children) {
      return true;
    }
    else if (this.props.isFocused !== nextProps.isFocused) {
      return true;
    }

    return false;
  }

  render() {
    let windowClassNames = classNames({
      'window': true,
      'focus': this.props.isFocused,
    });

    let barClassNames = classNames({
      'bar': true,
      'focus': this.props.isFocused,
    });

    return (
      <div className={windowClassNames}
        onClick={this.focus}
        ref={(ref) => this._windowRef = ref}>
        <div className={barClassNames}
          ref={(ref) => this._barRef = ref}>
          <button title="close" onClick={this.close}>X</button>
          <button title="save" onClick={this.download}>&#8681;</button>
          <div>{this.props.title}</div>
        </div>
        <div className="content">{this.props.children}</div>
      </div>
    );
  }
}

module.exports = Pane;
