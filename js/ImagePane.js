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

  handleDownload = () => {
    var link = document.createElement('a');
    link.download = `${this.props.title || 'visdom_image'}.jpg`;
    link.href = this.props.content.src;
    link.click();
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
        />
        <p className="caption">{content.caption}</p>
      </Pane>
    )
  }
}

module.exports = ImagePane;
