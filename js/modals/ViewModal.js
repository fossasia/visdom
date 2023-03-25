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
    onModalClose,
    onLayoutSave,
    onLayoutDelete,
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
          disabled={!connected || !selectText || selectText == DEFAULT_LAYOUT}
          onClick={() => onLayoutDelete(selectText)}
        >
          Delete
        </button>
      </div>
    </ReactModal>
  );
}

export default ViewModal;
