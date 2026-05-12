/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useContext, useEffect, useState } from 'react';
import ReactModal from 'react-modal';

import ApiContext from '../api/ApiContext';
import { DEFAULT_LAYOUT, MODAL_STYLE } from '../settings';

function ViewModal(props) {
  const { connected } = useContext(ApiContext);
  const {
    activeLayout,
    layoutList,
    envList,
    allLayoutLists,
    onModalClose,
    onLayoutSave,
    onLayoutDelete,
    onLayoutCopy,
    show,
  } = props;

  // effects
  // -------

  // change input / select value when activeLayout changes
  const [inputText, setInputText] = useState(activeLayout);
  const [selectText, setSelectText] = useState(activeLayout);
  useEffect(() => {
    setInputText(activeLayout);
    setSelectText(activeLayout);
  }, [activeLayout]);
  
  const [copyEnv, setCopyEnv] = useState(envList && envList.length > 0 ? envList[0]: '');
  useEffect(() => {
    if(envList && envList.length > 0 && !envList.includes(copyEnv)){
      setCopyEnv(envList[0]);
    }
  }, [envList]);

  const availableCopyLayouts = (allLayoutLists && allLayoutLists.has(copyEnv))
    ? Array.from(allLayoutLists.get(copyEnv).keys())
    : [];

    const hasLayouts = availableCopyLayouts.length > 0;
    const [copyLayout, setCopyLayout] = useState(hasLayouts ? availableCopyLayouts[0] : '');
    useEffect(() => {
      if (hasLayouts) {
        setCopyLayout(availableCopyLayouts[0]);
      } else {
        setCopyLayout('');
      }
    }, [copyEnv]);

    const [copyDestName, setCopyDestName] = useState('');
    useEffect(() => {
      setCopyDestName(copyLayout);
    }, [copyLayout]);
  // rendering
  // ---------
  return (
    <ReactModal
      isOpen={show}
      onRequestClose={onModalClose}
      contentLabel="Layout Views Management Modal"
      ariaHideApp={false}
      style={MODAL_STYLE}
    >
      <span className="visdom-title">Manage Views</span>
      <br />
      Save or fork current layout:
      <br />
      <div className="form-inline">
        <input
          className="form-control"
          type="text"
          value={inputText || ''}
          onChange={(ev) => {
            setInputText(ev.target.value);
          }}
        />
        <button
          className="btn btn-default"
          disabled={!connected || inputText == DEFAULT_LAYOUT}
          onClick={() => onLayoutSave(inputText)}
        >
          {layoutList.has(inputText) ? 'save' : 'fork'}
        </button>
      </div>
      <br />
      Delete layout view selected in dropdown:
      <br />
      <div className="form-inline">
        <select
          className="form-control"
          disabled={!connected}
          value={selectText}
          onChange={(ev) => {
            setSelectText(ev.target.value);
          }}
        >
          {Array.from(layoutList.keys()).map((view) => {
            return (
              <option key={view} value={view}>
                {view}
              </option>
            );
          })}
        </select>
        <button
          className="btn btn-default"
          disabled={!connected || !selectText || layoutList.size <= 1}
          onClick={() => onLayoutDelete(selectText)}
        >
          Delete
        </button>
      </div>
      <br />
      Copy layout view from another environment:
      <br />
      <div className="form-inline">
        <select
          className="form-control"
          disabled={!connected}
          value={copyEnv}
          onChange={(ev) => setCopyEnv(ev.target.value)}
          title="Source Environment"
        >
          {envList && envList.map((env) => (
            <option key={env} value={env}>{env}</option>
          ))}
        </select>
        <select
          className="form-control"
          disabled={!connected || !copyEnv || availableCopyLayouts.length === 0}
          value={copyLayout}
          onChange={(ev) => setCopyLayout(ev.target.value)}
          title="Source Layout"
        >
          {availableCopyLayouts.map((view) => (
            <option key={view} value={view}>{view}</option>
          ))}
        </select>
        <input
          className="form-control"
          type="text"
          value={copyDestName || ''}
          onChange={(ev) => setCopyDestName(ev.target.value)}
          title="New Layout Name"
          placeholder="New Name"
        />
        <button
          className="btn btn-default"
          disabled={!connected || !copyEnv || !copyLayout || !copyDestName}
          onClick={() => onLayoutCopy(copyEnv, copyLayout, copyDestName)}
        >
          Copy
        </button>
      </div>
    </ReactModal>
  );
}

export default ViewModal;
