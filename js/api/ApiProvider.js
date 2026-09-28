import $ from 'jquery';
import React, { useEffect, useRef, useState } from 'react';

import { showToast } from '../toasts/toastEvents';
import ApiContext from './ApiContext';
import Poller from './Legacy';
import serverPath from './serverPath';

const ApiProvider = ({ children }) => {
  const [connected, setConnected] = useState(false);
  const [sessionInfo, setSessionInfo] = useState({ id: null, readonly: false });
  const _socket = useRef(null);
  const apiHandlers = useRef(null);

  // ---------------- //
  // helper functions //
  // ---------------- //

  const correctPathname = serverPath;

  // ------------------- //
  // basic communication //
  // ------------------- //

  // Send a low-level message to the server
  const sendSocketMessage = (data) => {
    const socket = _socket.current;
    if (
      !socket ||
      (socket.readyState !== undefined && socket.readyState !== WebSocket.OPEN)
    ) {
      // eslint-disable-next-line no-console
      console.error(
        '[Visdom API] Cannot send message: WebSocket is not connected.',
        data
      );
      return false;
    }

    let msg = null;
    try {
      msg = JSON.stringify(data);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[Visdom API] Failed to serialize message:', e, data);
      return false;
    }

    try {
      socket.send(msg);
      return true;
    } catch (e) {
      // WebSocket may be CLOSING or CLOSED state
      // eslint-disable-next-line no-console
      console.error('[Visdom API] Failed to send message:', e, data);
      return false;
    }
  };

  // Establish a connection to the server
  const connect = () => {
    if (_socket.current) {
      return;
    }

    const _onConnect = () => {
      setConnected(true);
    };
    const _onDisconnect = () => {
      // Silent cleanup - logging handled by event handlers
      apiHandlers.current.onDisconnect(_socket);
      setConnected(false);
    };

    // eslint-disable-next-line no-undef
    if (USE_POLLING) {
      _socket.current = new Poller(
        correctPathname,
        handleMessage,
        _onConnect,
        _onDisconnect
      );
      return;
    }

    var url = window.location;
    var ws_protocol = null;
    if (url.protocol == 'https:') {
      ws_protocol = 'wss';
    } else {
      ws_protocol = 'ws';
    }

    const wsUrl = ws_protocol + '://' + url.host + correctPathname() + 'socket';

    var socket = new WebSocket(wsUrl);

    socket.onmessage = handleMessage;
    socket.onopen = _onConnect;
    socket.onerror = (event) => {
      // Log error but don't call _onDisconnect here (let onclose handle it)
      // eslint-disable-next-line no-console
      console.error(
        '[Visdom API] WebSocket error - the socket will likely close next',
        event
      );
    };
    socket.onclose = (event) => {
      // Determine if this was a clean close or an error
      if (!event.wasClean) {
        // eslint-disable-next-line no-console
        console.warn(
          '[Visdom API] WebSocket closed unexpectedly.',
          `Code: ${event.code}`,
          `Reason: ${event.reason || '(no reason provided)'}`
        );
      }
      // Only call _onDisconnect from onclose to avoid duplicate handling
      _onDisconnect();
    };
    _socket.current = socket;
  };

  // Close the server connection and reset the _socket ref
  const disconnect = () => {
    if (_socket.current) {
      _socket.current.close();
      _socket.current = null;
    }
  };

  // ------------------ //
  // API receive events //
  // -------------------//

  // Process messages received from the server by
  // implicitly defining event handlers for
  // different types of server-commands
  const syncTags = () => {
    $.ajax({
      url: correctPathname() + 'experiments/tags',
      method: 'GET',
      dataType: 'json',
      global: false,
    })
      .done((tags) => {
        apiHandlers.current.onTagsSync(tags);
      })
      .fail(() => {
        showToast('Unable to load environment tags.', 'error');
      });
  };

  const handleMessage = (evt) => {
    var cmd = JSON.parse(evt.data);
    switch (cmd.command) {
      case 'register':
        setSessionInfo((prev) => ({
          ...prev,
          id: cmd.data,
          readonly: cmd.readonly,
        }));
        if (cmd.envList) {
          apiHandlers.current.onEnvUpdate(cmd.envList);
        }
        syncTags();
        break;
      case 'pane':
      case 'window':
      case 'window_update':
        apiHandlers.current.onWindowMessage({
          cmd: cmd,
          update: cmd.command === 'window_update',
        });
        break;
      case 'reload':
        apiHandlers.current.onReloadMessage(cmd.data);
        break;
      case 'close':
        apiHandlers.current.onCloseMessage(cmd.data);
        break;
      case 'layout':
      case 'layout_update':
        apiHandlers.current.onLayoutMessage({
          data: cmd.data,
          update: cmd.command === 'layout_update',
        });
        break;
      case 'env_update':
        apiHandlers.current.onEnvUpdate(cmd.data);
        break;
      case 'tags_update':
        apiHandlers.current.onTagsUpdate(cmd.data);
        break;
      case 'undo_state':
        apiHandlers.current.onUndoState(cmd);
        break;
      case 'notification':
        showToast(cmd.data.message, cmd.data.type, {
          duration: cmd.data.duration,
        });
        break;

      default:
        // eslint-disable-next-line no-console
        console.error('unrecognized command', cmd);
    }
  };

  // we need to update the socket-callback so that we have an up-to date state
  if (_socket.current) _socket.current.onmessage = handleMessage;

  // --------------- //
  // API send events //
  // ----------------//

  // Request environment data from the server
  const sendEnvQuery = (envIDs, showAll) => {
    // This kicks off a new stream of events from the socket so there's nothing
    // to handle here. We might want to surface the error state.
    if (envIDs.length == 1) {
      $.post(
        correctPathname() + 'env/' + envIDs[0],
        JSON.stringify({
          sid: sessionInfo.id,
        })
      ).fail((xhr) => {
        document.open();
        document.write(xhr.responseText);
        document.close();
      });
    } else if (envIDs.length > 1) {
      $.post(
        correctPathname() + 'compare/' + envIDs.join('+'),
        JSON.stringify({
          sid: sessionInfo.id,
          show_all: !!showAll,
        })
      ).fail((xhr) => {
        document.open();
        document.write(xhr.responseText);
        document.close();
      });
    }
  };

  // Toggle connection state between online and offline
  const toggleOnlineState = () => {
    if (connected) {
      disconnect();
    } else {
      connect();
    }
  };

  // Send message to server backend for a specific pane and environment.
  const sendPaneMessage = (data, targetPaneID, targetEnvID) => {
    if (targetPaneID === null || sessionInfo.readonly) {
      return;
    }
    let finalData = {
      target: targetPaneID,
      eid: targetEnvID,
    };
    $.extend(finalData, data);
    sendSocketMessage({
      cmd: 'forward_to_vis',
      data: finalData,
    });
  };

  // Send request to revert to the previous set of embeddings in the given pane
  const sendEmbeddingPop = (data, targetPaneID, targetEnvID) => {
    if (targetPaneID === null || sessionInfo.readonly) {
      return;
    }
    let finalData = {
      target: targetPaneID,
      eid: targetEnvID,
    };
    $.extend(finalData, data);
    sendSocketMessage({
      cmd: 'pop_embeddings_pane',
      data: finalData,
    });
  };

  // Send request to close a specific pane
  const sendPaneClose = (paneID, envID) => {
    sendSocketMessage({
      cmd: 'close',
      data: paneID,
      eid: envID,
    });
  };

  const sendUndo = (envID) => {
    sendSocketMessage({
      cmd: 'undo',
      eid: envID,
    });
  };

  // Send request to delete an environment
  const sendEnvDelete = (envID, previousEnv) => {
    return sendSocketMessage({
      cmd: 'delete_env',
      prev_eid: previousEnv,
      eid: envID,
    });
  };

  // Send request to save the current environment
  const sendEnvSave = (envID, prev_envID, data) => {
    sendSocketMessage({
      cmd: 'save',
      data: data,
      prev_eid: prev_envID,
      eid: envID,
    });
  };

  // Replace or append key/value tags for one environment.
  const sendTagsUpdate = (envID, tags, append = false) => {
    return $.ajax({
      url: correctPathname() + 'experiments/tags',
      method: 'POST',
      contentType: 'application/json; charset=utf-8',
      dataType: 'json',
      data: JSON.stringify({
        action: 'set',
        eid: envID,
        tags: tags,
        append: append,
      }),
      global: false,
    });
  };

  const sendSaveAll = () => {
    sendSocketMessage({
      cmd: 'save_all',
    });
  };

  // Update the pane layout item in the backend.
  const sendPaneLayoutUpdate = (
    envID,
    { i, h, w, x, y, moved, static: staticBool }
  ) => {
    sendSocketMessage({
      cmd: 'layout_item_update',
      eid: envID,
      win: i,
      data: { i, h, w, x, y, moved, static: staticBool },
    });
  };

  const sendPlotLayoutUpdate = (envID, win, layoutPatch, frame) => {
    sendSocketMessage({
      cmd: 'update_plot_layout',
      eid: envID,
      win: win,
      data: layoutPatch,
      frame: frame,
    });
  };

  const sendCommentUpdate = (envID, win, comment) => {
    if (win === null || sessionInfo.readonly) {
      return;
    }
    sendSocketMessage({
      cmd: 'update_comment',
      eid: envID,
      win: win,
      data: comment,
    });
  };

  const sendTableEdit = (envID, win, op, data) => {
    if (win === null || sessionInfo.readonly) {
      return;
    }
    sendSocketMessage({
      cmd: 'table_edit',
      eid: envID,
      win: win,
      op: op,
      data: data,
    });
  };

  // Save layout lists to the server
  const sendLayoutsSave = (layoutLists) => {
    // pushes layouts to the server
    let objForm = {};
    for (let [envName, layoutList] of layoutLists) {
      objForm[envName] = {};
      for (let [layoutName, layoutMap] of layoutList) {
        objForm[envName][layoutName] = {};
        for (let [contentID, contentLoc] of layoutMap) {
          objForm[envName][layoutName][contentID] = contentLoc;
        }
      }
    }
    let exportForm = JSON.stringify(objForm);
    sendSocketMessage({
      cmd: 'save_layouts',
      data: exportForm,
    });
  };

  // ------- //
  // Effects //
  // ------- //

  // Redirect for POST request errors
  useEffect(() => {
    $(document).on('ajaxError', () => {
      window.location.href = correctPathname() + 'error/500';
    });

    return () => {
      $(document).off('ajaxError');
    };
  }, []);

  // connect on mount, disconnect on unmount
  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, []);

  // -------------- //
  // Define Context //
  // -------------- //
  return (
    <ApiContext.Provider
      value={{
        apiHandlers,
        connected,
        sendCommentUpdate,
        sendEmbeddingPop,
        sendEnvDelete,
        sendEnvQuery,
        sendEnvSave,
        sendLayoutsSave,
        sendTagsUpdate,
        sendPaneClose,
        sendPaneLayoutUpdate,
        sendPlotLayoutUpdate,
        sendPaneMessage,
        sendSaveAll,
        sendTableEdit,
        sendUndo,
        sessionInfo,
        setConnected,
        toggleOnlineState,
      }}
    >
      {children}
    </ApiContext.Provider>
  );
};

export default ApiProvider;
