/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useRef, useState } from 'react';

import EventSystem from './EventSystem';
import Pane from './Pane';

const DEFAULT_HEIGHT = 400;
const DEFAULT_WIDTH = 300;

function ImagePane(props) {
  const { title, type, selected, width, height, appApi } = props;
  var { content } = props;

  // state varibles
  // --------------
  const paneRef = useRef();
  const imgRef = useRef();
  const [view, setView] = useState({ scale: 1, tx: 0, ty: 0 });
  const [imgDim, setImgDim] = useState({ width: null, height: 0 });
  const [actualSelected, setActualSelected] = useState(props.selected);
  const [mouseLocation, setMouseLocation] = useState({
    x: 0,
    y: 0,
    visibility: 'hidden',
  });
  const [dragStart, setDragStart] = useState({
    x: 0,
    y: 0,
  });

  // private events
  // -------------
  const handleDownload = () => {
    var link = document.createElement('a');
    link.download = `${title || 'visdom_image'}.jpg`;
    link.href = content.src;
    link.click();
  };

  const handleZoom = (ev) => {
    if (ev.altKey) {
      //var direction = natural.checked ? -1 : 1;
      let direction = -1;
      // Get browser independent scaling factor
      let scrollDirectionX = Math.sign(ev.deltaX);
      let scrollDirectionY = Math.sign(ev.deltaY);
      // If shift is pressed only scroll sidewise (to allow scrolling
      // to the side by keep shift pressed and using normal scrolling
      // on the image pane)
      if (ev.shiftKey)
        setView({
          ...view,
          tx: view['tx'] + scrollDirectionY * direction * 50,
        });
      else
        setView({
          ...view,
          tx: view['tx'] + scrollDirectionX * direction * 50,
          ty: view['ty'] + scrollDirectionY * direction * 50,
        });
      ev.stopPropagation();
      ev.preventDefault();
    } else if (ev.ctrlKey) {
      // get the x and y offset of the pane
      let rect = paneRef.current.children[1].getBoundingClientRect();
      // Get browser independent scaling factor
      let scrollDirectionY = Math.sign(ev.deltaY);
      // Compute the coords of the mouse relative to the top left of the pane
      let xscreen = ev.clientX - rect.x;
      let yscreen = ev.clientY - rect.y;
      // Compute the coords of the pixel under the mouse wrt the image top left
      let ximage = (xscreen - view['tx']) / view['scale'];
      let yimage = (yscreen - view['ty']) / view['scale'];
      let new_scale = view['scale'] * Math.exp(-scrollDirectionY / 10);
      // Update the state.
      // The offset is modifed such that the pixel under the mouse
      // is the same after zooming
      setView({
        scale: new_scale,
        tx: xscreen - new_scale * ximage,
        ty: yscreen - new_scale * yimage,
      });
      ev.stopPropagation();
      ev.preventDefault();
    }
  };

  const handleDragStart = (ev) => {
    setDragStart({ x: ev.screenX, y: ev.screenY });
    ev.dataTransfer.setDragImage(new Image(), 0, 0); // disables ghost image
  };

  const handleDragOver = (ev) => {
    setView({
      scale: view['scale'],
      tx: view['tx'] + ev.screenX - dragStart.x,
      ty: view['ty'] + ev.screenY - dragStart.y,
    });
    setDragStart({ x: ev.screenX, y: ev.screenY });
  };

  const handleMouseOver = (ev) => {
    // get the x and y offset of the pane
    var rect = paneRef.current.children[1].getBoundingClientRect();
    // Compute the coords of the mouse relative to the top left of the pane
    var xscreen = ev.clientX - rect.x;
    var yscreen = ev.clientY - rect.y;
    // Compute the coords of the pixel under the mouse wrt the image top left
    var ximage = Math.round((xscreen - view['tx']) / view['scale']);
    var yimage = Math.round((yscreen - view['ty']) / view['scale']);
    setMouseLocation({
      x: ximage,
      y: yimage,
      visibility: ev.altKey ? 'visible' : 'hidden',
    });
  };

  const handleReset = () => {
    setView({
      scale: 1,
      tx: 0,
      ty: 0,
    });
  };

  const updateSlider = (evt) => {
    // TODO add history update events here! need to send these to the client
    // with sendPaneMessage
    setActualSelected(parseInt(evt.target.value));
  };

  // effects
  // -------

  // reset image selection upon property change
  useEffect(() => {
    setActualSelected(selected);
  }, [selected]);

  // Reset the image settings when the user resizes the window. Avoid
  // constantly resetting the zoom level when user has not zoomed.
  useEffect(() => {
    if (Math.abs(view['scale'] - 1) > Number.EPSILON) handleReset();
  }, [width, height]);

  // initialize mouse events
  useEffect(() => {
    const onEvent = (event) => {
      switch (event.type) {
        case 'keydown':
        case 'keypress':
          event.preventDefault();
          break;
        case 'keyup':
          appApi.sendPaneMessage({
            event_type: 'KeyPress',
            key: event.key,
            key_code: event.keyCode,
          });
          break;
        case 'click':
          appApi.sendPaneMessage({
            event_type: 'Click',
            image_coord: mouseLocation,
          });
          break;
      }
    };

    EventSystem.subscribe('global.event', onEvent);
    return function cleanup() {
      EventSystem.unsubscribe('global.event', onEvent);
    };
  }, [mouseLocation]);

  // image size/pos computation
  // --------------------------

  // Find the width/height that preserves the aspect ratio given 'scaledWidth/height'
  const computeHFromW = (scaledWidth) => {
    return Math.ceil((imgDim.height / imgDim.width) * scaledWidth);
  };
  const computeWFromH = (scaledHeight) => {
    return Math.ceil((imgDim.width / imgDim.height) * scaledHeight);
  };

  // compute image size & position
  let candidateWidth = Math.ceil(1 + width * view['scale']);
  let candidateHeight = Math.ceil(1 + height * view['scale']);
  let imageContainerStyle = {
    alignItems: 'row',
    display: 'flex',
    height: isNaN(candidateHeight) ? DEFAULT_HEIGHT : candidateHeight,
    justifyContent: 'center',
    width: isNaN(candidateWidth) ? DEFAULT_WIDTH : candidateWidth,
  };

  if (imgDim.height === null || imgDim.width === null) {
    // Do nothing, don't change the width/height
  } else if (candidateWidth >= candidateHeight) {
    // If the width exceeds the height, then we use the height as the limiting
    // factor
    let newWidth = computeWFromH(candidateHeight);
    // If the new width would exceed the window boundaries, we need to
    // instead use the window width as the limiting factor
    if (newWidth > candidateWidth) {
      candidateHeight = computeHFromW(candidateWidth);
      imageContainerStyle.alignItems = 'column';
    } else {
      candidateWidth = newWidth;
    }
  } else if (candidateWidth < candidateHeight) {
    // If the height exceeds the width, then we use the width as the limiting
    // factor
    let newHeight = computeHFromW(candidateWidth);
    // If the new height would exceed the window boundaries, we need to
    // instead use the window height as the limiting factor
    if (newHeight > candidateHeight) {
      candidateWidth = computeWFromH(candidateHeight);
    } else {
      imageContainerStyle.alignItems = 'column';
      candidateHeight = newHeight;
    }
  }

  // During initial render cycle,
  // Math.ceil(1 + height/width * view["scale"]) may be NaN.
  // Set a default value here to avoid warnings, which will be updated on the
  // next render

  if (isNaN(candidateHeight)) {
    candidateHeight = DEFAULT_HEIGHT;
  }

  if (isNaN(candidateWidth)) {
    candidateWidth = DEFAULT_WIDTH;
  }

  // rendering
  // ---------
  let widgets = [];
  const divstyle = { left: view['tx'], top: view['ty'], position: 'absolute' };

  // add image slider as widget
  if (type === 'image_history') {
    if (props.show_slider) {
      widgets.push(
        <div className="widget" key="image_slider">
          <div style={{ display: 'flex' }}>
            <span>Selected:&nbsp;&nbsp;</span>
            <input
              type="range"
              min="0"
              max={content.length - 1}
              value={actualSelected}
              onChange={updateSlider}
            />
            <span>&nbsp;&nbsp;{actualSelected}&nbsp;&nbsp;</span>
          </div>
        </div>
      );
    }
    content = content[actualSelected];
  }

  // add caption as widget
  if (content.caption) {
    widgets.splice(
      0,
      0,
      <span className="widget" key="img_caption">
        {content.caption}
      </span>
    );
  }

  return (
    <Pane
      {...props}
      handleDownload={handleDownload}
      handleReset={handleReset}
      handleZoom={handleZoom}
      handleMouseMove={handleMouseOver}
      ref={paneRef}
      widgets={widgets}
    >
      <div style={divstyle}>
        <div style={imageContainerStyle}>
          <img
            className="content-image cssTransforms"
            src={content.src}
            ref={imgRef}
            onLoad={() => {
              setImgDim({
                height: imgRef.current.naturalHeight,
                width: imgRef.current.naturalWidth,
              });
            }}
            width={candidateWidth + 'px'}
            height={candidateHeight + 'px'}
            onDoubleClick={handleReset}
            onDragStart={handleDragStart}
            onDragOver={handleDragOver}
          />
        </div>
      </div>
      <p className="caption">{content.caption}</p>
      <span
        className="mouse_image_location"
        style={{ visibility: mouseLocation.visibility }}
      >
        {mouseLocation.x + ' / ' + mouseLocation.y}
      </span>
    </Pane>
  );
}

export default ImagePane;
