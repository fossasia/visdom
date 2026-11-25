/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

/* Notes:
 * Width requires to know the DOM-Element of the Grid it wraps.
 * While this works in the current setup, for a refactored version
 * of main.js's App that uses function-components this function may break.
 * Also, eslint requires a displayName for every component that cannot be
 * inferred automatically in this cane, and also not set by hand.
 * Thus, we ignore these eslint-errors here for now.
 */

/* eslint-disable react/no-find-dom-node, react/display-name */

import './Width.css';

import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';

var Width = (ComposedComponent) => (props) => {
  const { onWidthChange, layout } = props;

  // state varibles
  // --------------
  const [width, setWidth] = useState(1280);
  const [cols, setCols] = useState(100);
  const containerRef = useRef();

  useLayoutEffect(() => {
    const container = containerRef.current;
    let resizeFrame = null;
    let restoreTransitions;
    let measuredWidth;
    const applyWidth = (nextWidth) => {
      measuredWidth = nextWidth;
      setCols((nextWidth / width) * cols);
      setWidth(nextWidth);
    };
    const onWindowResize = () => {
      if (resizeFrame !== null) return;
      resizeFrame = requestAnimationFrame(() => {
        resizeFrame = null;
        const nextWidth = container.offsetWidth;
        if (nextWidth === measuredWidth) return;
        container.classList.add('visdom-window-resizing');
        clearTimeout(restoreTransitions);
        applyWidth(nextWidth);
        restoreTransitions = setTimeout(() => {
          container.classList.remove('visdom-window-resizing');
        }, 150);
      });
    };

    // Measure before the first paint so incoming panes use the actual width.
    applyWidth(container.offsetWidth);
    window.addEventListener('resize', onWindowResize);
    return () => {
      window.removeEventListener('resize', onWindowResize);
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      clearTimeout(restoreTransitions);
      container.classList.remove('visdom-window-resizing');
    };
  }, []);

  useLayoutEffect(() => {
    onWidthChange(width, cols);
  }, [width]);

  const fittedLayout = useMemo(
    () =>
      layout.map((item) => {
        const w = Math.min(item.w, cols);
        const x = Math.max(0, Math.min(item.x, cols - w));
        return w === item.w && x === item.x ? item : { ...item, w, x };
      }),
    [layout, cols]
  );

  // rendering
  // ---------

  const {
    // eslint-disable-next-line no-unused-vars
    cols: propCols,
    rowHeight,
    margin,
    containerPadding,
    maxRows,
    useCSSTransforms,

    isDraggable,
    draggableHandle,
    dragBounded,
    draggableCancel,
    dragThreshold,

    isResizable,
    resizeHandles,

    ...restProps
  } = props;

  const gridConfig = {
    cols: cols,
    rowHeight: rowHeight !== undefined ? rowHeight : 150,
    margin: margin !== undefined ? margin : [10, 10],
    containerPadding: containerPadding !== undefined ? containerPadding : null,
    maxRows: maxRows !== undefined ? maxRows : Infinity,
    useCSSTransforms: useCSSTransforms !== undefined ? useCSSTransforms : true,
  };

  const dragConfig = {
    enabled: isDraggable !== false,
    handle: draggableHandle,
    cancel: draggableCancel,
    bounded: dragBounded !== undefined ? dragBounded : false,
    threshold: dragThreshold !== undefined ? dragThreshold : 3,
  };

  const resizeConfig = {
    enabled: isResizable !== false,
    handles: resizeHandles !== undefined ? resizeHandles : ['se'],
  };

  return (
    <div ref={containerRef} style={{ width: '100%' }}>
      <ComposedComponent
        {...restProps}
        layout={fittedLayout}
        width={width}
        gridConfig={gridConfig}
        dragConfig={dragConfig}
        resizeConfig={resizeConfig}
      />
    </div>
  );
};

export default Width;
