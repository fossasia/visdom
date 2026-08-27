/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

export const LATEX_STYLES = ['ieee', 'springer', 'generic'];

const DEFAULT_CAPTION = 'TODO: add caption';
const DEFAULT_EXT = 'png';

const LATEX_SPECIAL_CHARS = {
  '\\': '\\textbackslash{}',
  '{': '\\{',
  '}': '\\}',
  $: '\\$',
  '&': '\\&',
  '#': '\\#',
  '%': '\\%',
  _: '\\_',
  '^': '\\textasciicircum{}',
  '~': '\\textasciitilde{}',
  '<': '\\textless{}',
  '>': '\\textgreater{}',
};

export function escapeLatex(input) {
  if (input === null || input === undefined) return '';
  let str = String(input);
  str = str.replace(/\r\n|\r|\n/g, ' ').replace(/ {2,}/g, ' ');
  str = str.replace(/[\\{}$&#%_^~<>]/g, (ch) => LATEX_SPECIAL_CHARS[ch]);
  return str.trim();
}

function resolveCaption(caption) {
  const escaped = caption ? escapeLatex(caption) : '';
  return escaped.length > 0 ? escaped : DEFAULT_CAPTION;
}

export function slugify(input, fallback = 'figure') {
  if (input === null || input === undefined) return fallback;
  const slug = String(input)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || fallback;
}

export function buildLabel(contentID, fallbackId, prefix = 'fig') {
  return `${prefix}:${slugify(contentID, slugify(fallbackId))}`;
}

export function buildFilename(contentID, fallbackId, ext) {
  return `${slugify(contentID, slugify(fallbackId))}.${ext || DEFAULT_EXT}`;
}

function ieeeSingle({ filename, caption, label }) {
  return `\\begin{figure}[htbp]
\\centering
\\includegraphics[width=\\linewidth]{${filename}}
\\caption{${caption}}
\\label{${label}}
\\end{figure}`;
}

function springerSingle({ filename, caption, label }) {
  return `\\begin{figure}
\\centering
\\includegraphics[width=\\textwidth]{${filename}}
\\caption{${caption}}
\\label{${label}}
\\end{figure}`;
}

function genericSingle({ filename, caption, label }) {
  return `% Requires \\usepackage{graphicx} in your preamble.
\\begin{figure}[htbp]
  \\centering
  \\includegraphics[width=0.9\\linewidth]{${filename}}
  \\caption{${caption}}
  \\label{${label}}
\\end{figure}`;
}

function subWidth(n) {
  if (n <= 1) return '0.95';
  if (n === 2) return '0.48';
  if (n === 3) return '0.32';
  if (n === 4) return '0.24';
  return (0.95 / n).toFixed(2);
}

function ieeeCompare({ images, caption, label }) {
  const w = subWidth(images.length);
  const subs = images
    .map((img, idx) => {
      const hfill = idx < images.length - 1 ? '\n  \\hfill' : '';
      return `  \\begin{subfigure}[b]{${w}\\linewidth}
    \\centering
    \\includegraphics[width=\\linewidth]{${img.filename}}
    \\caption{${img.caption}}
    \\label{${img.label}}
  \\end{subfigure}${hfill}`;
    })
    .join('\n');
  return `% Requires \\usepackage{subcaption} in your preamble.
\\begin{figure}[htbp]
\\centering
${subs}
\\caption{${caption}}
\\label{${label}}
\\end{figure}`;
}

function springerCompare({ images, caption, label }) {
  const w = subWidth(images.length);
  const subs = images
    .map((img, idx) => {
      const hfill = idx < images.length - 1 ? '\n  \\hfill' : '';
      return `  \\begin{subfigure}{${w}\\textwidth}
    \\centering
    \\includegraphics[width=\\textwidth]{${img.filename}}
    \\caption{${img.caption}}
    \\label{${img.label}}
  \\end{subfigure}${hfill}`;
    })
    .join('\n');
  return `% Requires \\usepackage{subcaption} in your preamble.
\\begin{figure}
\\centering
${subs}
\\caption{${caption}}
\\label{${label}}
\\end{figure}`;
}

function genericCompare({ images, caption, label }) {
  const w = subWidth(images.length);
  const minipages = images
    .map(
      (img) => `  \\begin{minipage}{${w}\\linewidth}
    \\centering
    \\includegraphics[width=\\linewidth]{${img.filename}}
    \\par\\textbf{${img.caption}}
  \\end{minipage}%`
    )
    .join('\n  \\hfill\n');
  return `% Requires \\usepackage{graphicx} in your preamble.
% Sub-images use a plain bold label (not \\caption) on purpose: \\caption
% inside a minipage shares the same figure counter as top-level figures
% and would throw off numbering for the rest of the document. Only this
% figure's own \\caption below is numbered.
\\begin{figure}[htbp]
  \\centering
${minipages}
  \\caption{${caption}}
  \\label{${label}}
\\end{figure}`;
}

const SINGLE_TEMPLATES = {
  ieee: ieeeSingle,
  springer: springerSingle,
  generic: genericSingle,
};

const COMPARE_TEMPLATES = {
  ieee: ieeeCompare,
  springer: springerCompare,
  generic: genericCompare,
};

export function buildLatexSnippet(style, meta = {}) {
  if (!LATEX_STYLES.includes(style)) {
    throw new Error(`Unknown LaTeX export style: "${style}"`);
  }

  const fallbackId = meta.id || 'figure';
  const label = buildLabel(meta.contentID, fallbackId);
  const caption = resolveCaption(meta.caption);

  if (Array.isArray(meta.images) && meta.images.length > 0) {
    const images = meta.images.map((img, idx) => ({
      filename: buildFilename(img.id, `${fallbackId}-${idx + 1}`, img.ext),
      caption: resolveCaption(img.caption),
      label: `${label}-${idx + 1}`,
    }));
    return COMPARE_TEMPLATES[style]({ images, caption, label });
  }

  const filename = buildFilename(meta.contentID, fallbackId, meta.ext);
  return SINGLE_TEMPLATES[style]({ filename, caption, label });
}

function normalizeRow(row, columnCount) {
  if (!Array.isArray(row)) return new Array(columnCount).fill('');
  if (row.length === columnCount) return row;
  return Array.from({ length: columnCount }, (_, i) => row[i] ?? '');
}

function buildColSpec(columnCount, bordered) {
  if (!bordered) return 'c'.repeat(columnCount);
  return '|' + 'c|'.repeat(columnCount);
}

function buildHeaderRow(headers) {
  return (
    headers.map((h) => `\\textbf{${escapeLatex(h)}}`).join(' & ') + ' \\\\'
  );
}

function buildDataRows(rows, columnCount, indent = '', rowLines = false) {
  const separator = rowLines ? `\n${indent}\\hline\n` : '\n';
  return rows
    .map(
      (row) =>
        `${indent}${normalizeRow(row, columnCount)
          .map((cell) => escapeLatex(cell))
          .join(' & ')} \\\\`
    )
    .join(separator);
}

function ieeeTable({ colSpec, headerRow, dataRows, caption, label }) {
  const bodyLines = ['\\hline', headerRow, '\\hline'];
  if (dataRows) bodyLines.push(dataRows, '\\hline');
  return `\\begin{table}[htbp]
\\centering
\\caption{${caption}}
\\label{${label}}
\\begin{tabular}{${colSpec}}
${bodyLines.join('\n')}
\\end{tabular}
\\end{table}`;
}

function springerTable({ colSpec, headerRow, dataRows, caption, label }) {
  const bodyLines = ['\\hline', headerRow, '\\hline'];
  if (dataRows) bodyLines.push(dataRows, '\\hline');
  return `\\begin{table}
\\centering
\\caption{${caption}}
\\label{${label}}
\\begin{tabular}{${colSpec}}
${bodyLines.join('\n')}
\\end{tabular}
\\end{table}`;
}

function genericTable({ colSpec, headerRow, dataRows, caption, label }) {
  const bodyLines = ['    \\toprule', `    ${headerRow}`];
  if (dataRows) {
    bodyLines.push('    \\midrule', dataRows);
  }
  bodyLines.push('    \\bottomrule');
  return `% Requires \\usepackage{booktabs} in your preamble.
\\begin{table}[htbp]
  \\centering
  \\caption{${caption}}
  \\label{${label}}
  \\begin{tabular}{${colSpec}}
${bodyLines.join('\n')}
  \\end{tabular}
\\end{table}`;
}

const TABLE_TEMPLATES = {
  ieee: ieeeTable,
  springer: springerTable,
  generic: genericTable,
};

export function buildLatexTableSnippet(style, meta = {}) {
  if (!LATEX_STYLES.includes(style)) {
    throw new Error(`Unknown LaTeX export style: "${style}"`);
  }

  const headers = Array.isArray(meta.headers) ? meta.headers : [];
  const rows = Array.isArray(meta.rows) ? meta.rows : [];
  const columnCount = headers.length;

  if (columnCount === 0) {
    return '% This table has no columns -- nothing to export.';
  }

  const fallbackId = meta.id || 'table';
  const label = buildLabel(meta.contentID, fallbackId, 'tab');
  const caption = resolveCaption(meta.caption);
  const bordered = style !== 'generic';
  const colSpec = buildColSpec(columnCount, bordered);
  const headerRow = buildHeaderRow(headers);
  const dataRows = buildDataRows(
    rows,
    columnCount,
    style === 'generic' ? '    ' : '',
    bordered
  );

  return TABLE_TEMPLATES[style]({
    colSpec,
    headerRow,
    dataRows,
    caption,
    label,
  });
}

function legacyCopyToClipboard(text) {
  return new Promise((resolve, reject) => {
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.top = '-1000px';
      textarea.style.left = '-1000px';
      textarea.style.opacity = '0';
      textarea.setAttribute('readonly', '');
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      const successful = document.execCommand('copy');
      document.body.removeChild(textarea);
      if (successful) resolve();
      else reject(new Error('document.execCommand("copy") returned false'));
    } catch (err) {
      reject(err);
    }
  });
}

export function copyTextToClipboard(text) {
  const hasModernClipboard =
    typeof navigator !== 'undefined' &&
    navigator.clipboard &&
    typeof navigator.clipboard.writeText === 'function' &&
    typeof window !== 'undefined' &&
    window.isSecureContext;

  if (hasModernClipboard) {
    return navigator.clipboard
      .writeText(text)
      .catch(() => legacyCopyToClipboard(text));
  }
  return legacyCopyToClipboard(text);
}

export async function copyLatexToClipboard(style, meta) {
  const snippet = buildLatexSnippet(style, meta);
  return copyTextToClipboard(snippet);
}

export async function copyLatexTableToClipboard(style, meta) {
  const snippet = buildLatexTableSnippet(style, meta);
  return copyTextToClipboard(snippet);
}
