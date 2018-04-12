/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const Pane = require('./Pane');

class ImagePane extends React.Component {
  _paneRef = null;

  state: State = {
    scale: 1.,
    tx: 0.,
    ty: 0.,
  }

  handleDownload = () => {
    var link = document.createElement('a');
    link.download = `${this.props.title || 'visdom_image'}.jpg`;
    link.href = this.props.content.src;
    link.click();
  }

  handleZoom = (ev) => {
    if(ev.shiftKey) {
      //var direction = natural.checked ? -1 : 1;
      var direction =  -1;
      this.setState({tx: this.state.tx + ev.deltaX * direction});
      this.setState({ty: this.state.ty + ev.deltaY * direction});
      ev.stopPropagation();
      ev.preventDefault();
    } else if (ev.ctrlKey) {
      var s = Math.exp(-ev.deltaY/100);
      this.setState({scale: this.state.scale * s});
      ev.stopPropagation();
      ev.preventDefault();
    }
  }

  handleReset = () => {
    this.setState({
      scale: 1.,
      tx: 0.,
      ty: 0.
    });
  }

  render() {
    let content = this.props.content;
    const divstyle = {
      left: this.state.tx,
      top: this.state.ty,
      position: "relative",
      display: "block",
    };
    return (
      <Pane
        {...this.props}
        handleDownload={this.handleDownload}
        handleReset={this.handleReset.bind(this)}
        handleZoom={this.handleZoom.bind(this)}
        ref={(ref) => this._paneRef = ref}>
        <div style={divstyle}>
          <img
            className="content-image cssTransforms"
            src={content.src}
            width={Math.ceil(1 + this.props.width * this.state.scale) + "px"}
            height={Math.ceil(1 + this.props.height * this.state.scale) + "px"}
            onDoubleClick={this.handleReset.bind(this)}
            />
        </div>
        <p className="caption">{content.caption}</p>
      </Pane>
    )
  }
}

module.exports = ImagePane;
