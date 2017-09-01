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
  }

  handleDownload = () => {
    var link = document.createElement('a');
    link.download = `${this.props.title || 'visdom_image'}.jpg`;
    link.href = this.props.content.src;
    link.click();
  }

  handleZoom = (ev) => {
     let delta = (ev.deltaMode === ev.DOM_DELTA_PIXEL) ? ev.deltaY :
                                                         ev.deltaY * 40;
     let scalefactor = Math.exp(-delta / 5000.);
     this.setState(
        {scale: this.state.scale * scalefactor}
     );
     ev.stopPropagation();
     ev.preventDefault();
  }

  resetZoom = (ev) => {
     this.setState(
       {scale: 1.}
    );
  }

  render() {
    let content = this.props.content;
    return (
      <Pane
        {...this.props}
        handleDownload={this.handleDownload}
        ref={(ref) => this._paneRef = ref}>
        <img
          className="content-image"
          src={content.src}
          width={Math.ceil(1 + this.props.width * this.state.scale) + "px"}
          height={Math.ceil(1 + this.props.height * this.state.scale) + "px"}
          onWheel={this.handleZoom.bind(this)}
          onDoubleClick={this.resetZoom.bind(this)}
        />
        <p className="caption">{content.caption}</p>
      </Pane>
    )
  }
}

module.exports = ImagePane;
