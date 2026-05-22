/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import TreeSelect, { SHOW_CHILD } from 'rc-tree-select';
import React, { useContext, useState } from 'react';

import ApiContext from '../api/ApiContext';

function EnvControls(props) {
  const { connected, sessionInfo, sendSaveAll } = useContext(ApiContext);
  const readonly = sessionInfo.readonly;
  const {
    envList,
    envIDs,
    envSelectorStyle,
    onEnvSelect,
    onEnvClear,
    onEnvManageButton,
  } = props;
  const [confirmClear, setConfirmClear] = useState(false);

  // tree select setup
  // -------
  var slist = envList.slice();
  slist.sort();

  var childrenByPrefix = {};
  slist.forEach((env) => {
    var idx = env.indexOf('_');
    if (idx > 0) {
      var prefix = env.substring(0, idx);
      if (!childrenByPrefix[prefix]) childrenByPrefix[prefix] = [];
      childrenByPrefix[prefix].push(env);
    }
  });

  var keyCounter = 1;
  var env_options2 = [];
  var parentKeys = {};

  Object.keys(childrenByPrefix).sort().forEach((prefix) => {
    parentKeys[prefix] = keyCounter;
    env_options2.push({
      key: keyCounter++,
      pId: 0,
      label: prefix,
      value: '__group__' + prefix,
    });
  });

  slist.forEach((env) => {
    var idx = env.indexOf('_');
    var prefix = idx > 0 ? env.substring(0, idx) : null;
    var parentKey = 0;

    if (prefix && parentKeys[prefix] !== undefined) {
      parentKey = parentKeys[prefix];
    } else if (parentKeys[env] !== undefined) {
      parentKey = parentKeys[env];
    }

    env_options2.push({
      key: keyCounter++,
      pId: parentKey,
      label: env,
      value: env,
    });
  });

  const currentIdx = envIDs.length > 0 ? slist.indexOf(envIDs[0]) : -1;
  const hasSingleSelectedEnv = envIDs.length === 1 && currentIdx !== -1;
  const onPrevEnv = () => {
    if (hasSingleSelectedEnv && currentIdx > 0) {
      onEnvSelect([slist[currentIdx - 1]]);
    }
  };
  const onNextEnv = () => {
    if (hasSingleSelectedEnv && currentIdx < slist.length - 1) {
      onEnvSelect([slist[currentIdx + 1]]);
    }
  };
  const isDisabled = !connected || readonly || !hasSingleSelectedEnv;
  const isAtStart = isDisabled || currentIdx <= 0;
  const isAtEnd = isDisabled || currentIdx >= slist.length - 1;

  // rendering
  // ---------
  return (
    <span>
      <span>Environment&nbsp;</span>
      <div
        className="btn-group navbar-btn"
        role="group"
        aria-label="Environment:"
      >
        <div className="btn-group" role="group">
          <TreeSelect
            style={envSelectorStyle}
            allowClear={true}
            dropdownStyle={{
              maxHeight: 900,
              overflow: 'auto',
              wordBreak: 'break-all',
            }}
            placeholder={<i>Select environment(s)</i>}
            searchPlaceholder="search"
            treeLine
            maxTagTextLength={1000}
            inputValue={null}
            value={envIDs}
            treeData={env_options2}
            treeDefaultExpandAll
            treeNodeFilterProp="title"
            treeDataSimpleMode={{ id: 'key', rootPId: 0 }}
            treeCheckable
            showCheckedStrategy={SHOW_CHILD}
            dropdownMatchSelectWidth={false}
            onChange={onEnvSelect}
          />
          {slist.length > 1 && (
            <div className="env-arrow-wrapper">
              <button
                aria-label="Previous Environment"
                className="env-arrow-btn"
                title="Previous Environment"
                disabled={isAtStart}
                onClick={onPrevEnv}
              >
                ▲
              </button>
              <button
                aria-label="Next Environment"
                className="env-arrow-btn"
                title="Next Environment"
                disabled={isAtEnd}
                onClick={onNextEnv}
              >
                ▼
              </button>
            </div>
          )}
        </div>
        <button
          id="clear-button"
          data-toggle="tooltip"
          title={confirmClear ? 'Are you sure?' : 'Clear Current Environment'}
          data-placement="bottom"
          className={confirmClear ? 'btn btn-warning' : 'btn btn-default'}
          disabled={!(connected && envIDs.length > 0 && !readonly)}
          onClick={() => {
            if (confirmClear) {
              onEnvClear();
              setConfirmClear(false);
            } else setConfirmClear(true);
          }}
          onBlur={() => setConfirmClear(false)}
        >
          <span className="glyphicon glyphicon-erase" />
        </button>
        <button
          data-toggle="tooltip"
          title="Save All Environments"
          data-placement="bottom"
          className="btn btn-default"
          disabled={!(connected && !readonly)}
          onClick={sendSaveAll}
        >
          <span className="glyphicon glyphicon-floppy-disk" />
        </button>
        <button
          data-toggle="tooltip"
          title="Manage Environments"
          data-placement="bottom"
          className="btn btn-default"
          disabled={!(connected && envIDs.length > 0 && !readonly)}
          onClick={onEnvManageButton}
        >
          <span className="glyphicon glyphicon-folder-open" />
        </button>
      </div>
    </span>
  );
}

export default EnvControls;
