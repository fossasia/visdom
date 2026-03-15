/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useContext, useEffect } from 'react';
import ScrollToBottom from 'react-scroll-to-bottom';

import ApiContext from '../api/ApiContext';
import EventSystem from '../EventSystem';
import Pane from './Pane';

function TextPane(props) {
  const { sendPaneMessage } = useContext(ApiContext);
  const { envID, id, content, isFocused } = props;

  // private events
  // --------------
  const onEvent = (e) => {
    if (!isFocused) return;

    switch (e.type) {
      case 'keydown':
      case 'keypress':
        e.preventDefault();
        break;
      case 'keyup':
        sendPaneMessage(
          {
            event_type: 'KeyPress',
            key: e.key,
            key_code: e.keyCode,
          },
          id,
          envID
        );
        break;
    }
  };

  // define action for Pane's download button
  const handleDownload = () => {
    var blob = new Blob([content], { type: 'text/plain' });
    var url = window.URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.download = 'visdom_text.txt';
    link.href = url;
    link.click();
  };

  // effects
  // -------

  // registers instance with EventSystem
  useEffect(() => {
    EventSystem.subscribe('global.event', onEvent);
    return function cleanup() {
      EventSystem.unsubscribe('global.event', onEvent);
    };
  });

  // rendering
  // ---------

  const LARGE_BACKLOG_CONTENT_LENGTH = 50000;
  const initialScrollBehavior =
    content && content.length > LARGE_BACKLOG_CONTENT_LENGTH
      ? 'auto'
      : 'smooth';

  return (
    <Pane {...props} handleDownload={handleDownload}>
      <ScrollToBottom
        className="content-text"
        scrollViewClassName="content-text-scroll-view"
        followButtonClassName="content-text-follow-button"
        initialScrollBehavior={initialScrollBehavior}
        mode="bottom"
      >
        <div dangerouslySetInnerHTML={{ __html: content }} />
      </ScrollToBottom>
    </Pane>
  );
}

export default TextPane;
