/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { Pencil } from 'lucide-react';
import React, { useContext, useEffect, useRef, useState } from 'react';

import ApiContext from '../api/ApiContext';
import { showToast } from '../toasts/toastEvents';
import Pane from './Pane';
import PropertyItem from './PropertyItem';
import { copyLatexTableToClipboard } from './utils/LatexExport';

const DEFAULT_COL_WIDTH = 120;
const DEFAULT_ROW_HEIGHT = 28;
const MIN_COL_WIDTH = 40;
const MIN_ROW_HEIGHT = 18;

function TablePane(props) {
  const { sendTableEdit, sessionInfo } = useContext(ApiContext);
  const { envID, id, contentID, content } = props;
  const { headers = [], rows = [] } = content || {};
  const canEdit = props.editable !== false && !sessionInfo?.readonly;
  const [locked, setLocked] = useState(false);
  const editable = canEdit && !locked;

  const [colWidths, setColWidths] = useState(() =>
    headers.map(() => DEFAULT_COL_WIDTH)
  );
  const [rowHeights, setRowHeights] = useState(() =>
    rows.map(() => DEFAULT_ROW_HEIGHT)
  );
  const dragState = useRef(null);
  const tableRef = useRef(null);

  useEffect(() => {
    setColWidths((w) => headers.map((_, i) => w[i] ?? DEFAULT_COL_WIDTH));
  }, [headers.length]);

  useEffect(() => {
    setRowHeights((h) => rows.map((_, i) => h[i] ?? DEFAULT_ROW_HEIGHT));
  }, [rows.length]);

  useEffect(() => {
    return () => {
      if (dragState.current) {
        document.removeEventListener('mousemove', dragState.current.onMove);
        document.removeEventListener('mouseup', dragState.current.onUp);
        dragState.current = null;
      }
    };
  }, []);

  // private events
  // --------------

  const editCell = (r, c, value) =>
    sendTableEdit(envID, id, 'edit_cell', { row: r, col: c, value });
  const editHeader = (c, value) =>
    sendTableEdit(envID, id, 'edit_header', { col: c, value });
  const addRow = () =>
    sendTableEdit(envID, id, 'add_row', { values: headers.map(() => '') });
  const deleteRow = (r) => sendTableEdit(envID, id, 'delete_row', { row: r });
  const addCol = () =>
    sendTableEdit(envID, id, 'add_col', {
      name: `Column ${headers.length + 1}`,
    });
  const deleteCol = (c) => sendTableEdit(envID, id, 'delete_col', { col: c });

  const startResize = (kind, idx, ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const startPos = kind === 'col' ? ev.clientX : ev.clientY;
    const startSize =
      kind === 'col'
        ? (colWidths[idx] ?? DEFAULT_COL_WIDTH)
        : (rowHeights[idx] ?? DEFAULT_ROW_HEIGHT);
    const minSize = kind === 'col' ? MIN_COL_WIDTH : MIN_ROW_HEIGHT;

    const onMove = (moveEv) => {
      const pos = kind === 'col' ? moveEv.clientX : moveEv.clientY;
      const delta = pos - startPos;
      const newSize = Math.max(minSize, startSize + delta);
      if (kind === 'col') {
        setColWidths((w) => {
          const next = [...w];
          next[idx] = newSize;
          return next;
        });
      } else {
        setRowHeights((h) => {
          const next = [...h];
          next[idx] = newSize;
          return next;
        });
      }
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      dragState.current = null;
    };
    dragState.current = { onMove, onUp };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  };

  const handleDownload = () => {
    const escapeCsv = (v) => {
      let s = String(v);
      if (/^[=+\-@\t\r]/.test(s)) {
        s = `'${s}`;
      }
      return `"${s.replace(/"/g, '""')}"`;
    };
    const csv = [headers, ...rows]
      .map((r) => r.map(escapeCsv).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.download = 'visdom_table.csv';
    link.href = url;
    link.click();
    setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  };

  const handleLatexExport = (style) => {
    if (headers.length === 0) {
      showToast('This Table has no columns to export', 'error', {
        position: 'bottom-center',
        shape: 'pill',
        duration: 1500,
      });
      return;
    }
    copyLatexTableToClipboard(style, {
      contentID,
      id,
      caption: props.title,
      headers,
      rows,
    })
      .then(() =>
        showToast('Copied!', 'success', {
          position: 'bottom-center',
          shape: 'pill',
          duration: 1500,
        })
      )
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error('TablePane LaTeX export failed:', err);
        showToast('Failed to Copy', 'error', {
          position: 'bottom-center',
          shape: 'pill',
          duration: 1500,
        });
      });
  };

  // rendering
  // ---------

  const totalWidth =
    colWidths.reduce((sum, w) => sum + w, 0) + (editable ? 24 : 0);

  const editToggleButton = canEdit ? (
    <button
      key="table-edit-toggle-button"
      title={
        editable
          ? 'Lock editing for yourself'
          : 'Editing is locked for yourself -- click to unlock'
      }
      aria-pressed={editable}
      onClick={() => {
        const active = document.activeElement;
        if (
          tableRef.current &&
          active &&
          tableRef.current.contains(active) &&
          typeof active.blur === 'function'
        ) {
          active.blur();
        }
        setLocked((v) => !v);
      }}
      className={
        editable
          ? 'table-edit-toggle pull-right active'
          : 'table-edit-toggle pull-right'
      }
    >
      <Pencil size={11} />
    </button>
  ) : (
    ''
  );

  return (
    <Pane
      {...props}
      handleDownload={handleDownload}
      handleLatexExport={handleLatexExport}
      barwidgets={[editToggleButton]}
    >
      <div className="content-table" ref={tableRef}>
        <table
          className="table-native"
          style={{ tableLayout: 'fixed', width: totalWidth }}
        >
          <colgroup>
            {colWidths.map((w, i) => (
              <col key={i} style={{ width: w }} />
            ))}
            {editable && <col style={{ width: 24 }} />}
          </colgroup>
          <thead>
            <tr>
              {headers.map((h, c) => (
                <th key={c} className="table-header-cell">
                  <div className="table-header-inner">
                    {editable ? (
                      <PropertyItem
                        type="text"
                        value={h}
                        propId={c}
                        updateValue={(_, value) => editHeader(c, value)}
                        blurStopPropagation={true}
                      />
                    ) : (
                      <span className="table-header-text">{h}</span>
                    )}
                    {editable && (
                      <button
                        type="button"
                        className="table-delete-col"
                        title="Delete column"
                        onClick={() => deleteCol(c)}
                      >
                        ×
                      </button>
                    )}
                  </div>
                  {editable && (
                    <div
                      className="col-resize-handle"
                      aria-hidden="true"
                      onMouseDown={(ev) => startResize('col', c, ev)}
                    />
                  )}
                </th>
              ))}
              {editable && (
                <th className="table-add-col">
                  <button type="button" title="Add column" onClick={addCol}>
                    +
                  </button>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => {
              const cells =
                row.length === headers.length
                  ? row
                  : headers.map((_, i) => row[i] ?? '');
              return (
                <tr key={r} style={{ height: rowHeights[r] }}>
                  {cells.map((cell, c) => {
                    const isFirst = c === 0;
                    if (!editable) {
                      return (
                        <td key={c} className="table-cell table-cell-readonly">
                          {cell}
                        </td>
                      );
                    }
                    return (
                      <td
                        key={c}
                        className={
                          isFirst ? 'table-cell table-cell-first' : 'table-cell'
                        }
                      >
                        <div className="table-cell-inner">
                          <PropertyItem
                            type="text"
                            value={cell}
                            propId={c}
                            updateValue={(_, value) => editCell(r, c, value)}
                            blurStopPropagation={true}
                          />
                          {isFirst && (
                            <button
                              type="button"
                              className="table-delete-row"
                              title="Delete row"
                              onClick={() => deleteRow(r)}
                            >
                              ×
                            </button>
                          )}
                        </div>
                        {isFirst && (
                          <div
                            className="row-resize-handle"
                            aria-hidden="true"
                            onMouseDown={(ev) => startResize('row', r, ev)}
                          />
                        )}
                      </td>
                    );
                  })}
                  {editable && <td />}
                </tr>
              );
            })}
            {editable && (
              <tr>
                <td colSpan={headers.length + 1} className="table-add-row">
                  <button type="button" onClick={addRow}>
                    + Add row
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Pane>
  );
}

export default TablePane;
