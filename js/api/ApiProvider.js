import $ from 'jquery';
import React, { useEffect, useRef, useState } from 'react';

import ApiContext from './ApiContext';
import Poller from './Legacy';

const ApiProvider = ({ children }) => {
  const [connected, setConnected] = useState(false);
  const [sessionInfo, setSessionInfo] = useState({ id: null, readonly: false });
  const _socket = useRef(null);
  const apiHandlers = useRef(null);

  // ---------------- //
  // helper functions //
  // ---------------- //

  // Normalize window.location by removing specific path segments
  // and ensuring the pathname ends with a '/'
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

  // Send a low-level message to the server
  const sendSocketMessage = (data) => {
    if (!_socket.current) {
      // TODO: error? warn?
      return;
    }

    let msg = JSON.stringify(data);
    return _socket.current.send(msg);
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
    var socket = new WebSocket(
      ws_protocol + '://' + url.host + correctPathname() + 'socket'
    );

    socket.onmessage = handleMessage;
    socket.onopen = _onConnect;
    socket.onerror = socket.onclose = _onDisconnect;
    _socket.current = socket;
  };

  // Close the server connection and reset the _socket ref
  const disconnect = () => {
    _socket.current.close();
    _socket.current = null;
  };

  // ------------------ //
  // API receive events //
  // -------------------//

  // Process messages received from the server by
  // implicitly defining event handlers for
  // different types of server-commands
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
        apiHandlers.current.onWindowMessage({
          cmd: cmd,
          update: cmd.commmand == 'window_update',
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
          cmd: cmd.data,
          update: cmd.commmand == 'layout_update',
        });
        break;
      case 'env_update':
        apiHandlers.current.onEnvUpdate(cmd.data);
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

  // Request environment data from the server
  const sendEnvQuery = (envIDs) => {
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

  // Send request to delete an environment
  const sendEnvDelete = (envID, previousEnv) => {
    sendSocketMessage({
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
        sendEmbeddingPop,
        sendEnvDelete,
        sendEnvQuery,
        sendEnvSave,
        sendLayoutsSave,
        sendPaneClose,
        sendPaneLayoutUpdate,
        sendPaneMessage,
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
