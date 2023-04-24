import $ from 'jquery';
import React, { useEffect, useRef, useState } from 'react';

import ApiContext from './ApiContext';
import Poller from './Legacy';

const ApiProvider = ({ children }) => {
  const [connected, setConnected] = useState(false);
  const [sessionInfo, setSessionInfo] = useState({ id: null, readonly: false });
  const _socket = useRef(null);
  const onHandlers = useRef(null);

  // ---------------- //
  // helper functions //
  // ---------------- //

  // retrieve normalized window.location
  const correctPathname = () => {
    var pathname = window.location.pathname;
    if (pathname.indexOf('/env/') > -1) {
      pathname = pathname.split('/env/')[0];
    } else if (pathname.indexOf('/compare/') > -1) {
      pathname = pathname.split('/compare/')[0];
    }
    if (pathname.slice(-1) != '/') {
      pathname = pathname + '/';
    }
    return pathname;
  };

  // ------------------- //
  // basic communication //
  // ------------------- //

  // low-level message to server
  const sendSocketMessage = (data) => {
    if (!_socket.current) {
      // TODO: error? warn?
      return;
    }

    let msg = JSON.stringify(data);
    return _socket.current.send(msg);
  };

  // connect to server
  const connect = () => {
    if (_socket.current) {
      return;
    }

    const _onConnect = () => {
      setConnected(true);
    };
    const _onDisconnect = () => {
      onHandlers.current.onDisconnect(_socket);
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
    var socket = new WebSocket(
      ws_protocol + '://' + url.host + correctPathname() + 'socket'
    );

    socket.onmessage = handleMessage;
    socket.onopen = _onConnect;
    socket.onerror = socket.onclose = _onDisconnect;
    _socket.current = socket;
  };

  // close server connection
  const disconnect = () => {
    _socket.current.close();
    _socket.current = null;
  };

  // ------------------ //
  // API receive events //
  // -------------------//

  // handle server messages
  const handleMessage = (evt) => {
    var cmd = JSON.parse(evt.data);
    switch (cmd.command) {
      case 'register':
        setSessionInfo((prev) => ({
          ...prev,
          id: cmd.data,
          readonly: cmd.readonly,
        }));
        break;
      case 'pane':
      case 'window':
      case 'window_update':
        onHandlers.current.onWindowMessage({
          cmd: cmd,
          update: cmd.commmand == 'window_update',
        });
        break;
      case 'reload':
        onHandlers.current.onReloadMessage(cmd.data);
        break;
      case 'close':
        onHandlers.current.onCloseMessage(cmd.data);
        break;
      case 'layout':
      case 'layout_update':
        onHandlers.current.onLayoutMessage({
          cmd: cmd.data,
          update: cmd.commmand == 'layout_update',
        });
        break;
      case 'env_update':
        onHandlers.current.onEnvUpdate(cmd.data);
        break;

      default:
        console.error('unrecognized command', cmd);
    }
  };

  // we need to update the socket-callback so that we have an up-to date state
  if (_socket.current) _socket.current.onmessage = handleMessage;

  // --------------- //
  // API send events //
  // ----------------//

  // query env from server
  const postForEnv = (envIDs) => {
    // This kicks off a new stream of events from the socket so there's nothing
    // to handle here. We might want to surface the error state.
    if (envIDs.length == 1) {
      $.post(
        correctPathname() + 'env/' + envIDs[0],
        JSON.stringify({
          sid: sessionInfo.id,
        })
      );
    } else if (envIDs.length > 1) {
      $.post(
        correctPathname() + 'compare/' + envIDs.join('+'),
        JSON.stringify({
          sid: sessionInfo.id,
        })
      );
    }
  };

  const toggleOnlineState = () => {
    if (connected) {
      disconnect();
    } else {
      connect();
    }
  };

  /**
   * Send message to backend.
   *
   * The `data` object is extended by pane and environment Id.
   * Note: Only focused panes should call this method.
   *
   * @param data Data to be sent to backend.
   */
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

  const sendClosePane = (paneID, envID) => {
    sendSocketMessage({
      cmd: 'close',
      data: paneID,
      eid: envID,
    });
  };

  const sendDeleteEnv = (envID, previousEnv) => {
    sendSocketMessage({
      cmd: 'delete_env',
      prev_eid: previousEnv,
      eid: envID,
    });
  };

  const sendEnvSave = (envID, prev_envID, data) => {
    sendSocketMessage({
      cmd: 'save',
      data: data,
      prev_eid: prev_envID,
      eid: envID,
    });
  };

  /**
   * Send layout item state to backend to update backend state.
   *
   * @param layout Layout to be sent to backend.
   */
  const sendLayoutItemState = (
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

  const exportLayoutsToServer = (layoutLists) => {
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
        connected,
        sessionInfo,
        setConnected,
        onHandlers,
        postForEnv,
        sendPaneMessage,
        sendEmbeddingPop,
        exportLayoutsToServer,
        toggleOnlineState,
        sendEnvSave,
        sendDeleteEnv,
        sendClosePane,
        sendLayoutItemState,
      }}
    >
      {children}
    </ApiContext.Provider>
  );
};

export default ApiProvider;
