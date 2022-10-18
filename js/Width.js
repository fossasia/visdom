/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom';

const Width = (ComposedComponent) => (props) => {
  const { onWidthChange } = props;

  // state varibles
  // --------------
  const [width, setWidth] = useState(1280);
  const [cols, setCols] = useState(100);
  const [timerActive, setTimerActive] = useState(false);
  const containerRef = useRef();

  // private events
  // --------------

  // when resizing, set timer to trigger onWindowResizeStop
  // (retriggers setTimer setup)
  const onWindowResize = () => {
    setTimerActive(false);
    setTimerActive(true);
  };

  // when resizing finished, save dimensions & trigger onWidthChange
  const onWindowResizeStop = () => {
    // reenable timer activation
    setTimerActive(false);

    // get new dimensions
    const node = ReactDOM.findDOMNode(containerRef.current);
    setCols((node.offsetWidth / width) * cols);
    setWidth(node.offsetWidth);
  };

  // effects
  // -------

  // when setting timerActive activates timer
  // note: this activates actual timer after rendering to ensure only one
  //       timer is running at a time
  useEffect(() => {
    if (!timerActive) return;
    let resizeTimer = setTimeout(onWindowResizeStop, 200);
    return function cleanup() {
      clearTimeout(resizeTimer);
    };
  }, [timerActive]);

  // actual onWidthChange occurs only, when the state variables changed
  useEffect(() => {
    onWidthChange(width, cols);
  }, [width]);

  // ensure that resizing callbacks are only called when mounted
  useEffect(() => {
    window.addEventListener('resize', onWindowResize);
    return function cleanup() {
      window.removeEventListener('resize', onWindowResize);
    };
  }, []);

  // call onWindowResize upon initialization to query initial dimensions
  useEffect(() => {
    onWindowResize();
  }, []);

  // rendering
  // ---------

  return (
    <ComposedComponent
      {...props}
      ref={containerRef}
      width={width}
      cols={cols}
    />
  );
};

export default Width;
