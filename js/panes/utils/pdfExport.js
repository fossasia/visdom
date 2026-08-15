/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { showToast } from '../../toasts/toastEvents';

const POINTS_PER_INCH = 72;
const DEFAULT_CAPTURE_DPI = 96;

function dataUrlToBytes(dataUrl) {
  const base64 = dataUrl.substring(dataUrl.indexOf(',') + 1);
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

function readJpegInfo(bytes) {
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) {
    throw new Error('Not a valid JPEG (missing SOI marker)');
  }

  let pos = 2;
  while (pos < bytes.length - 1) {
    if (bytes[pos] !== 0xff) {
      throw new Error('Malformed JPEG marker stream');
    }
    while (pos < bytes.length && bytes[pos] === 0xff) {
      pos++;
    }
    if (pos >= bytes.length) {
      throw new Error('Malformed JPEG marker stream (truncated)');
    }
    const marker = bytes[pos];
    pos += 1;

    if (
      marker === 0xd8 ||
      marker === 0xd9 ||
      marker === 0x01 ||
      (marker >= 0xd0 && marker <= 0xd7)
    ) {
      continue;
    }

    const length = (bytes[pos] << 8) | bytes[pos + 1];

    const isSofMarker =
      marker >= 0xc0 &&
      marker <= 0xcf &&
      marker !== 0xc4 &&
      marker !== 0xc8 &&
      marker !== 0xcc;

    if (isSofMarker) {
      const height = (bytes[pos + 3] << 8) | bytes[pos + 4];
      const width = (bytes[pos + 5] << 8) | bytes[pos + 6];
      const numComponents = bytes[pos + 7];
      return { width, height, numComponents };
    }

    if (marker === 0xda) {
      break;
    }

    pos += length;
  }

  throw new Error('Could not find JPEG dimensions (no SOF marker)');
}

function colorSpaceFor(numComponents) {
  if (numComponents === 1) return '/DeviceGray';
  if (numComponents === 4) return '/DeviceCMYK';
  return '/DeviceRGB';
}

function buildPdfParts(jpegBytes, info, captureDpi) {
  const colorSpace = colorSpaceFor(info.numComponents);
  const pageWidthPt = Math.round((info.width / captureDpi) * POINTS_PER_INCH);
  const pageHeightPt = Math.round((info.height / captureDpi) * POINTS_PER_INCH);

  const parts = [];
  const objectOffsets = [];
  let cursor = 0;

  const pushText = (str) => {
    parts.push(str);
    cursor += str.length;
  };
  const pushBytes = (bytes) => {
    parts.push(bytes);
    cursor += bytes.byteLength;
  };
  const markObjectStart = () => {
    objectOffsets.push(cursor);
  };

  pushText('%PDF-1.4\n');

  markObjectStart();
  pushText('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n');

  markObjectStart();
  pushText('2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n');

  markObjectStart();
  pushText(
    '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ' +
      pageWidthPt +
      ' ' +
      pageHeightPt +
      '] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>\nendobj\n'
  );

  markObjectStart();
  pushText(
    '4 0 obj\n<< /Type /XObject /Subtype /Image /Width ' +
      info.width +
      ' /Height ' +
      info.height +
      ' /ColorSpace ' +
      colorSpace +
      ' /BitsPerComponent 8 /Filter /DCTDecode /Length ' +
      jpegBytes.byteLength +
      ' >>\nstream\n'
  );
  pushBytes(jpegBytes);
  pushText('\nendstream\nendobj\n');

  markObjectStart();
  const contentStream =
    'q ' + pageWidthPt + ' 0 0 ' + pageHeightPt + ' 0 0 cm /Im0 Do Q';
  pushText(
    '5 0 obj\n<< /Length ' +
      contentStream.length +
      ' >>\nstream\n' +
      contentStream +
      '\nendstream\nendobj\n'
  );

  const xrefOffset = cursor;
  let xref =
    'xref\n0 ' + (objectOffsets.length + 1) + '\n0000000000 65535 f \n';
  for (const offset of objectOffsets) {
    xref += String(offset).padStart(10, '0') + ' 00000 n \n';
  }
  pushText(xref);

  pushText(
    'trailer\n<< /Size ' +
      (objectOffsets.length + 1) +
      ' /Root 1 0 R >>\nstartxref\n' +
      xrefOffset +
      '\n%%EOF'
  );

  return parts;
}

export function downloadImageAsPdf(
  dataUrl,
  filename,
  captureDpi = DEFAULT_CAPTURE_DPI
) {
  try {
    const jpegBytes = dataUrlToBytes(dataUrl);
    const info = readJpegInfo(jpegBytes);
    const parts = buildPdfParts(jpegBytes, info, captureDpi);
    const blob = new Blob(parts, { type: 'application/pdf' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  } catch (err) {
    showToast('Failed to build PDF', 'error', { duration: 4000 });
    // eslint-disable-next-line no-console
    console.error('downloadImageAsPdf: failed to build PDF -', err);
  }
}
