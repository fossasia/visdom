/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import TreeSelect, { SHOW_CHILD } from 'rc-tree-select';
import React, { useState } from 'react';

function EnvControls(props) {
  const {
    connected,
    envList,
    envIDs,
    readonly,
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
  var roots = Array.from(
    new Set(
      slist.map((x) => {
        return x.split('_')[0];
      })
    )
  );

  let env_options2 = slist.map((env, idx) => {
    if (env.split('_').length == 1) {
      return null;
    }
    return {
      key: idx + 1 + roots.length,
      pId: roots.indexOf(env.split('_')[0]) + 1,
      label: env,
      value: env,
    };
  });

  env_options2 = env_options2.filter((x) => x != null);

  env_options2 = env_options2.concat(
    roots.map((x, idx) => {
      return {
        key: idx + 1,
        pId: 0,
        label: x,
        value: x,
      };
    })
  );

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
