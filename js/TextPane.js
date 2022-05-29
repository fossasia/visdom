/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect } from 'react';
import EventSystem from './EventSystem';
import Pane from './Pane';

function TextPane(props) {
  const onEvent = (e) => {
    if (!props.isFocused) return;

    switch (e.type) {
      case 'keydown':
      case 'keypress':
        e.preventDefault();
        break;
      case 'keyup':
        props.appApi.sendPaneMessage({
          event_type: 'KeyPress',
          key: e.key,
          key_code: e.keyCode,
        });
        break;
    }
  };

  // registers instance with EventSystem
  useEffect(() => {
    EventSystem.subscribe('global.event', onEvent);
    return function cleanup() {
      EventSystem.unsubscribe('global.event', onEvent);
    };
  });

  // define action for Pane's download button
  const handleDownload = () => {
    var blob = new Blob([props.content], { type: 'text/plain' });
    var url = window.URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.download = 'visdom_text.txt';
    link.href = url;
    link.click();
  };

  return (
    <Pane {...props} handleDownload={handleDownload}>
      <div className="content-text">
        <div dangerouslySetInnerHTML={{ __html: props.content }} />
      </div>
    </Pane>
  );
}

export default TextPane;
