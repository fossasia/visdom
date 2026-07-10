/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

const EXIT_ANIMATION_MS = 200;

const Toast = ({
  message,
  type = 'info',
  duration = 4000,
  shape = 'rect',
  onDismiss,
}) => {
  const [isLeaving, setIsLeaving] = useState(false);
  const isLeavingRef = useRef(false);
  const dismissTimerRef = useRef(null);
  const exitTimerRef = useRef(null);
  const onDismissRef = useRef(onDismiss);

  useEffect(() => {
    onDismissRef.current = onDismiss;
  }, [onDismiss]);

  const startExit = useCallback(() => {
    if (isLeavingRef.current) return;
    isLeavingRef.current = true;
    setIsLeaving(true);
    exitTimerRef.current = setTimeout(
      () => onDismissRef.current(),
      EXIT_ANIMATION_MS
    );
  }, []);

  useEffect(() => {
    if (duration > 0) {
      dismissTimerRef.current = setTimeout(startExit, duration);
    }
    return () => {
      clearTimeout(dismissTimerRef.current);
      clearTimeout(exitTimerRef.current);
    };
  }, [duration, startExit]);

  const isPill = shape === 'pill';

  const className = [
    'visdom-toast',
    `visdom-toast-${type}`,
    isPill ? 'visdom-toast-pill' : '',
    isLeaving ? 'visdom-toast-leaving' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={className} role="alert">
      <span className="visdom-toast-message">{message}</span>

      {!isPill && (
        <button
          aria-label="Dismiss notification"
          className="visdom-toast-close"
          onClick={startExit}
          type="button"
        >
          &times;
        </button>
      )}

      {!isPill && duration > 0 && !isLeaving && (
        <div
          className="visdom-toast-progress"
          style={{ animationDuration: `${duration}ms` }}
        />
      )}
    </div>
  );
};

export default Toast;
