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
    mouse_location: {x: 0., y: 0, visibility: 'hidden'},
  }

  drag_start_x = null;
  drag_start_y = null;

  onEvent = (event) => {
    if (!this.props.isFocused) {
      return;
    }

    switch (event.type) {
      case 'keydown':
      case 'keypress':
        event.preventDefault();
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
      // Get browser independend scaling factor 
      var scrollDirectionX = Math.sign(ev.deltaX);
      var scrollDirectionY = Math.sign(ev.deltaY);
      // If shift is pressed only scroll sidewise (to allow scrolling to the side by keep shift pressed and using normal scrolling on the image pane)
      if(ev.shiftKey){
        this.setState({tx: this.state.tx + scrollDirectionY * direction*50});
      }
      else {
        this.setState({tx: this.state.tx + scrollDirectionX * direction*50});
        this.setState({ty: this.state.ty + scrollDirectionY * direction*50});
      }
      ev.stopPropagation();
      ev.preventDefault();
    } else if (ev.ctrlKey) {
      // get the x and y offset of the pane
      var rect = this._paneRef._windowRef.children[1].getBoundingClientRect();
      // Get browser independendgit scaling factor
      var scrollDirectionY = Math.sign(ev.deltaY);
      // Compute the coords of the mouse relative to the top left of the pane
      var xscreen = ev.clientX - rect.x;
      var yscreen = ev.clientY - rect.y;
      // Compute the coords of the pixel under the mouse wrt the image top left
      var ximage = (xscreen - this.state.tx) / this.state.scale;
      var yimage = (yscreen - this.state.ty) / this.state.scale;
      var new_scale = this.state.scale * Math.exp(-scrollDirectionY/10);
      // Update the state.
      // The offset is modifed such that the pixel under the mouse
      // is the same after zooming
      this.setState({
        scale: new_scale,
        tx: xscreen - new_scale*ximage,
        ty: yscreen - new_scale*yimage
      });
      ev.stopPropagation();
      ev.preventDefault();
    }
  }

  handleDragStart = (ev) => {
    this.drag_start_x = ev.screenX;
    this.drag_start_y = ev.screenY;
  }

  handleDragOver = (ev) => {
    this.setState({
      tx: this.state.tx + ev.screenX - this.drag_start_x,
      ty: this.state.ty + ev.screenY - this.drag_start_y,
    });
    this.drag_start_x = ev.screenX;
    this.drag_start_y = ev.screenY;
  }

  handleMouseOver = (ev) => {
    // get the x and y offset of the pane
    if (ev.altKey){
      var rect = this._paneRef._windowRef.children[1].getBoundingClientRect();
      // Compute the coords of the mouse relative to the top left of the pane
      var xscreen = ev.clientX - rect.x;
      var yscreen = ev.clientY - rect.y;
      // Compute the coords of the pixel under the mouse wrt the image top left
      var ximage = Math.round((xscreen - this.state.tx) / this.state.scale);
      var yimage = Math.round((yscreen - this.state.ty) / this.state.scale);
      this.setState({mouse_location: {x: ximage, y: yimage, visibility: 'visible'}});
    } else {
      this.setState({mouse_location: {x: 0, y: 0, visibility: 'hidden'}});
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
      position: "absolute",
    };
    return (
      <Pane
        {...this.props}
        handleDownload={this.handleDownload}
        handleReset={this.handleReset.bind(this)}
        handleZoom={this.handleZoom.bind(this)}
        handleMouseMove={this.handleMouseOver.bind(this)}
        ref={(ref) => this._paneRef = ref}>
        <div style={divstyle}>
          <img
            className="content-image cssTransforms"
            src={content.src}
            width={Math.ceil(1 + this.props.width * this.state.scale) + "px"}
            height={Math.ceil(1 + this.props.height * this.state.scale) + "px"}
            onDoubleClick={this.handleReset.bind(this)}
            onDragStart={this.handleDragStart.bind(this)}
            onDragOver={this.handleDragOver.bind(this)}
            />
        </div>
        <p className="caption">{content.caption}</p>
        <span
          className="mouse_image_location"
          style={{visibility: this.state.mouse_location.visibility}}>
          {this.state.mouse_location.x + ' / ' + this.state.mouse_location.y}
        </span>
      </Pane>
    )
  }
}

module.exports = ImagePane;
