/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

function normalizeDpi(dpi) {
  const n = Math.round(Number(dpi));
  if (!Number.isFinite(n) || n <= 0) return 96;
  return Math.min(n, 65535);
}

function dataUrlToBytes(dataUrl) {
  const base64 = dataUrl.substring(dataUrl.indexOf(',') + 1);
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

function writeUint32BE(bytes, offset, value) {
  bytes[offset] = (value >>> 24) & 0xff;
  bytes[offset + 1] = (value >>> 16) & 0xff;
  bytes[offset + 2] = (value >>> 8) & 0xff;
  bytes[offset + 3] = value & 0xff;
}

function triggerBlobDownload(bytes, mimeType, filename) {
  const blob = new Blob([bytes], { type: mimeType });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}

function isJfifApp0At(bytes, pos) {
  return (
    bytes[pos] === 0xff &&
    bytes[pos + 1] === 0xe0 &&
    bytes[pos + 4] === 0x4a &&
    bytes[pos + 5] === 0x46 &&
    bytes[pos + 6] === 0x49 &&
    bytes[pos + 7] === 0x46 &&
    bytes[pos + 8] === 0x00
  );
}

function setJpegDpi(jpegBytes, dpi) {
  if (jpegBytes[0] !== 0xff || jpegBytes[1] !== 0xd8) {
    throw new Error('Not a valid JPEG (missing SOI marker)');
  }
  const safeDpi = normalizeDpi(dpi);

  if (isJfifApp0At(jpegBytes, 2)) {
    const out = jpegBytes.slice();
    out[2 + 11] = 1;
    out[2 + 12] = (safeDpi >> 8) & 0xff;
    out[2 + 13] = safeDpi & 0xff;
    out[2 + 14] = (safeDpi >> 8) & 0xff;
    out[2 + 15] = safeDpi & 0xff;
    return out;
  }

  const app0 = new Uint8Array(18);
  app0[0] = 0xff;
  app0[1] = 0xe0;
  app0[2] = 0x00;
  app0[3] = 0x10;
  app0[4] = 0x4a;
  app0[5] = 0x46;
  app0[6] = 0x49;
  app0[7] = 0x46;
  app0[8] = 0x00;
  app0[9] = 0x01;
  app0[10] = 0x02;
  app0[11] = 0x01;
  app0[12] = (safeDpi >> 8) & 0xff;
  app0[13] = safeDpi & 0xff;
  app0[14] = (safeDpi >> 8) & 0xff;
  app0[15] = safeDpi & 0xff;
  app0[16] = 0x00;
  app0[17] = 0x00;

  const out = new Uint8Array(2 + app0.length + (jpegBytes.length - 2));
  out[0] = 0xff;
  out[1] = 0xd8;
  out.set(app0, 2);
  out.set(jpegBytes.subarray(2), 2 + app0.length);
  return out;
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) {
    crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

function readChunkHeader(bytes, pos) {
  const length =
    ((bytes[pos] << 24) |
      (bytes[pos + 1] << 16) |
      (bytes[pos + 2] << 8) |
      bytes[pos + 3]) >>>
    0;
  const type = String.fromCharCode(
    bytes[pos + 4],
    bytes[pos + 5],
    bytes[pos + 6],
    bytes[pos + 7]
  );
  return { length, type, totalLength: 4 + 4 + length + 4 };
}

function buildPhysChunk(pixelsPerMeter) {
  const data = new Uint8Array(9);
  writeUint32BE(data, 0, pixelsPerMeter);
  writeUint32BE(data, 4, pixelsPerMeter);
  data[8] = 1;

  const chunk = new Uint8Array(4 + 4 + 9 + 4);
  writeUint32BE(chunk, 0, 9);
  chunk[4] = 0x70;
  chunk[5] = 0x48;
  chunk[6] = 0x59;
  chunk[7] = 0x73;
  chunk.set(data, 8);
  const crc = crc32(chunk.subarray(4, 17));
  writeUint32BE(chunk, 17, crc);
  return chunk;
}

function setPngDpi(pngBytes, dpi) {
  for (let i = 0; i < 8; i++) {
    if (pngBytes[i] !== PNG_SIGNATURE[i]) {
      throw new Error('Not a valid PNG (bad signature)');
    }
  }

  const pixelsPerMeter = Math.round(normalizeDpi(dpi) / 0.0254);
  const physChunk = buildPhysChunk(pixelsPerMeter);

  let pos = 8;
  let insertAt = -1;
  while (pos < pngBytes.length) {
    const { length, type, totalLength } = readChunkHeader(pngBytes, pos);

    if (type === 'pHYs') {
      const out = pngBytes.slice();
      const dataStart = pos + 8;
      out.set(physChunk.subarray(8, 17), dataStart);
      const crc = crc32(out.subarray(pos + 4, pos + 4 + 4 + length));
      writeUint32BE(out, dataStart + length, crc);
      return out;
    }

    if (type === 'IHDR' && insertAt === -1) {
      insertAt = pos + totalLength;
    }
    if (type === 'IDAT' || type === 'IEND') {
      break;
    }
    pos += totalLength;
  }

  if (insertAt === -1) {
    throw new Error('Could not find IHDR chunk');
  }

  const out = new Uint8Array(pngBytes.length + physChunk.length);
  out.set(pngBytes.subarray(0, insertAt), 0);
  out.set(physChunk, insertAt);
  out.set(pngBytes.subarray(insertAt), insertAt + physChunk.length);
  return out;
}

export function downloadJpegWithDpi(dataUrl, filename, dpi) {
  try {
    const bytes = dataUrlToBytes(dataUrl);
    const stamped = setJpegDpi(bytes, dpi);
    triggerBlobDownload(stamped, 'image/jpeg', filename);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error('downloadJpegWithDpi: failed to embed DPI metadata -', err);
    try {
      triggerBlobDownload(dataUrlToBytes(dataUrl), 'image/jpeg', filename);
    } catch (fallbackErr) {
      // eslint-disable-next-line no-console
      console.error(
        'downloadJpegWithDpi: fallback download also failed -',
        fallbackErr
      );
    }
  }
}

export function downloadPngWithDpi(dataUrl, filename, dpi) {
  try {
    const bytes = dataUrlToBytes(dataUrl);
    const stamped = setPngDpi(bytes, dpi);
    triggerBlobDownload(stamped, 'image/png', filename);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error('downloadPngWithDpi: failed to embed DPI metadata -', err);
    try {
      triggerBlobDownload(dataUrlToBytes(dataUrl), 'image/png', filename);
    } catch (fallbackErr) {
      // eslint-disable-next-line no-console
      console.error(
        'downloadPngWithDpi: fallback download also failed -',
        fallbackErr
      );
    }
  }
}
