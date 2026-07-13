/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import './toast.less';

import React, { useCallback, useEffect, useState } from 'react';

import EventSystem from '../EventSystem';
import Toast from './Toast';

const POSITIONS = [
  'top-left',
  'top-center',
  'top-right',
  'bottom-left',
  'bottom-center',
  'bottom-right',
];

const ToastContainer = () => {
  const [toasts, setToasts] = useState([]);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    const handleToast = (toast) => {
      setToasts((prev) => [...prev, toast]);
    };
    const handleDismiss = ({ id }) => {
      removeToast(id);
    };

    EventSystem.subscribe('toast', handleToast);
    EventSystem.subscribe('toast-dismiss', handleDismiss);

    return () => {
      EventSystem.unsubscribe('toast', handleToast);
      EventSystem.unsubscribe('toast-dismiss', handleDismiss);
    };
  }, [removeToast]);

  if (toasts.length === 0) {
    return null;
  }

  return (
    <>
      {POSITIONS.map((position) => {
        const positionToasts = toasts.filter(
          (t) => (t.position || 'top-right') === position
        );
        if (positionToasts.length === 0) return null;

        return (
          <div
            className={`visdom-toast-container
                        visdom-toast-container-${position}`
            }
            key={position}
          >
            {positionToasts.map((toast) => (
              <Toast
                duration={toast.duration}
                key={toast.id}
                message={toast.message}
                onDismiss={() => removeToast(toast.id)}
                shape={toast.shape}
                type={toast.type}
              />
            ))}
          </div>
        );
      })}
    </>
  );
};

export default ToastContainer;
