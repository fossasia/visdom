/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import EventSystem from "./EventSystem";
const Pane = require('./Pane');

class ImagePane extends React.Component {
  _paneRef = null;

  state: State = {
    scale: 1.,
    tx: 0.,
    ty: 0.,
    selected: this.props.selected,
  }

  componentWillReceiveProps = (nextProps) => {
    if (nextProps.selected !== this.props.selected) {
      this.setState({selected: nextProps.selected});
    }
  }

  onEvent = (e) => {
    if(!this.props.isFocused) {
      return;
    }

    switch(e.type) {
      case 'keydown':
      case 'keypress':
        e.preventDefault();
        break;
      case 'keyup':
        this.props.appApi.sendPaneMessage(
          {
            event_type: 'KeyPress',
            key: event.key,
            key_code: event.keyCode,
          }
        );
        break;
    }
  };

  componentDidMount() {
    EventSystem.subscribe('global.event', this.onEvent)
  }
  componentWillMount() {
    EventSystem.unsubscribe('global.event', this.onEvent)
  }

  handleDownload = () => {
    var link = document.createElement('a');
    link.download = `${this.props.title || 'visdom_image'}.jpg`;
    link.href = this.props.content.src;
    link.click();
  }

  handleZoom = (ev) => {
    if(ev.altKey) {
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

  updateSlider = (evt) => {
    // TODO add history update events here! need to send these to the client
    // with sendPaneMessage
    this.setState({
      selected: evt.target.value,
    });
  }

  render() {
    let content = this.props.content;
    let type = this.props.type;
    let widgets = []

    if (type == 'image_history') {
      let selected = this.state.selected;
      if (this.props.show_slider) {
        widgets.push(
          <div className="widget">
            <div style={{display: 'flex'}}>
              <span>Selected:&nbsp;&nbsp;</span>
              <input
                type="range"
                min="0"
                max={content.length-1}
                value={this.state.selected}
                onInput={this.updateSlider.bind(this)}
              />
              <span>&nbsp;&nbsp;{this.state.selected}&nbsp;&nbsp;</span>
            </div>
          </div>
        );
      }
      content = content[selected]
    }

    if (content.caption) {
      widgets.splice(0, 0, <span className="widget">{content.caption}</span>);
    }

    // TODO use this widget_height somehow to adjust window height!!!
    let widget_height = 30 * widgets.length - 10;

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
        ref={(ref) => this._paneRef = ref}
        widgets={widgets}>
        <div style={divstyle}>
          <img
            className="content-image cssTransforms"
            src={content.src}
            width={Math.ceil(1 + this.props.width * this.state.scale) + "px"}
            height={Math.ceil(1 + this.props.height * this.state.scale) + "px"}
            onDoubleClick={this.handleReset.bind(this)}
            />
        </div>
      </Pane>
    )
  }
}

module.exports = ImagePane;
