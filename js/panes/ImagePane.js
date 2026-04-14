/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useContext, useEffect, useRef, useState } from 'react';

import ApiContext from '../api/ApiContext';
import EventSystem from '../EventSystem';
import Pane from './Pane';

const DEFAULT_HEIGHT = 400;
const DEFAULT_WIDTH = 300;

function ImagePane(props) {
  const { sendPaneMessage } = useContext(ApiContext);
  const { envID, id, title, type, selected, width, height } = props;
  var { isFocused, content } = props;

  // state variables
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
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  // private events
  // --------------

  const handleDownload = () => {
    var link = document.createElement('a');
    link.download = `${title || 'visdom_image'}.jpg`;
    link.href = content.src;
    link.click();
  };

  const handleZoom = (ev) => {
    if (ev.altKey) {
      let direction = -1;
      let scrollDirectionX = Math.sign(ev.deltaX);
      let scrollDirectionY = Math.sign(ev.deltaY);

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
      let rect = paneRef.current.children[1].getBoundingClientRect();
      let scrollDirectionY = Math.sign(ev.deltaY);

      let xscreen = ev.clientX - rect.x;
      let yscreen = ev.clientY - rect.y;

      let ximage = (xscreen - view['tx']) / view['scale'];
      let yimage = (yscreen - view['ty']) / view['scale'];

      let new_scale = view['scale'] * Math.exp(-scrollDirectionY / 10);

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
    ev.dataTransfer.setDragImage(new Image(), 0, 0);
  };

  const handleDragOver = (ev) => {
    setView({
      scale: view['scale'],
      tx: view['tx'] + ev.screenX - dragStart.x,
      ty: view['ty'] + ev.screenY - dragStart.y,
    });
    setDragStart({ x: ev.screenX, y: ev.screenY });
  };

  /**
   * FIX: Calculate mouse coordinates relative to actual image
   */
  const handleMouseOver = (ev) => {
    if (!imgRef.current || !imgDim.width || !imgDim.height) return;

    const rect = imgRef.current.getBoundingClientRect();

    const x = ev.clientX - rect.left;
    const y = ev.clientY - rect.top;

    const xPercent = x / rect.width;
    const yPercent = y / rect.height;

    const xImage = Math.round(xPercent * imgDim.width);
    const yImage = Math.round(yPercent * imgDim.height);

    setMouseLocation({
      x: xImage,
      y: yImage,
      visibility: ev.altKey ? 'visible' : 'hidden',
    });
  };

  const handleReset = () => {
    setView({ scale: 1, tx: 0, ty: 0 });
  };

  const updateSlider = (evt) => {
    setActualSelected(parseInt(evt.target.value));
  };

  // effects
  // -------

  useEffect(() => {
    setActualSelected(selected);
  }, [selected]);

  useEffect(() => {
    if (Math.abs(view['scale'] - 1) > Number.EPSILON) handleReset();
  }, [width, height]);

  useEffect(() => {
    const onEvent = (event) => {
      switch (event.type) {
        case 'keydown':
        case 'keypress':
          event.preventDefault();
          break;
        case 'keyup':
          if (isFocused)
            sendPaneMessage(
              {
                event_type: 'KeyPress',
                key: event.key,
                key_code: event.keyCode,
              },
              id,
              envID
            );
          break;
        case 'click':
          if (isFocused)
            sendPaneMessage(
              {
                event_type: 'Click',
                image_coord: mouseLocation,
              },
              id,
              envID
            );
          break;
      }
    };

    EventSystem.subscribe('global.event', onEvent);
    return () => EventSystem.unsubscribe('global.event', onEvent);
  }, [mouseLocation, isFocused, id, envID, sendPaneMessage]);

  // rendering
  // ---------

  let candidateWidth = Math.ceil(1 + width * view['scale']);
  let candidateHeight = Math.ceil(1 + height * view['scale']);

  if (isNaN(candidateHeight)) candidateHeight = DEFAULT_HEIGHT;
  if (isNaN(candidateWidth)) candidateWidth = DEFAULT_WIDTH;

  let widgets = [];
  const divstyle = { left: view['tx'], top: view['ty'], position: 'absolute' };

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
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <img
            className="content-image cssTransforms"
            alt={content.caption}
            src={content.src}
            ref={imgRef}
            onLoad={() => {
              setImgDim({
                height: imgRef.current.naturalHeight,
                width: imgRef.current.naturalWidth,
              });
            }}
            width={candidateWidth}
            height={candidateHeight}
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