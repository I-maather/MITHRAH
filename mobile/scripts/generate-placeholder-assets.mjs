#!/usr/bin/env node
/**
 * توليد صور نائبة صالحة (PNG) للأيقونة وشاشة البدء.
 *
 * These are PLACEHOLDERS, not artwork and not Apple assets. They are generated
 * here — rather than committed as opaque binaries — so anyone can see exactly
 * what bytes end up in the bundle. Replace them before any submission.
 *
 * No external dependency: the PNG is assembled by hand (IHDR/IDAT/IEND with
 * zlib deflate from Node's own stdlib).
 *
 *     node scripts/generate-placeholder-assets.mjs
 */
import { deflateSync } from 'node:zlib';
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ASSETS = join(HERE, '..', 'assets');

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c;
  }
  return table;
})();

function crc32(buffer) {
  let c = 0xffffffff;
  for (let i = 0; i < buffer.length; i += 1) {
    c = CRC_TABLE[(c ^ buffer[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeAndData = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typeAndData), 0);
  return Buffer.concat([length, typeAndData, crc]);
}

/**
 * @param {number} size  square edge in px
 * @param {[number,number,number]} bg
 * @param {[number,number,number]} fg
 * @param {number} markRatio  size of the centred mark, 0..1
 */
function makePng(size, bg, fg, markRatio) {
  const raw = Buffer.alloc(size * (size * 4 + 1));
  const inner = Math.round(size * markRatio);
  const start = Math.round((size - inner) / 2);
  const end = start + inner;
  const ring = Math.max(2, Math.round(inner * 0.16));

  let offset = 0;
  for (let y = 0; y < size; y += 1) {
    raw[offset] = 0; // filter: none
    offset += 1;
    for (let x = 0; x < size; x += 1) {
      const insideBox = x >= start && x < end && y >= start && y < end;
      const insideHole =
        x >= start + ring && x < end - ring && y >= start + ring && y < end - ring;
      // علامة بسيطة: إطار مربع مفتوح من الأسفل — لا شعار ولا محاكاة لأي علامة.
      const openBottom = y >= end - ring && x > start + ring && x < end - ring;
      const on = insideBox && !insideHole && !openBottom;
      const [r, g, b] = on ? fg : bg;
      raw[offset] = r;
      raw[offset + 1] = g;
      raw[offset + 2] = b;
      raw[offset + 3] = 255;
      offset += 4;
    }
  }

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // colour type RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// ألوان النسق: ليل 950 خلفيةً، وأثل الداكن علامةً.
const NIGHT = [12, 14, 16];
const ATHL = [92, 201, 190];
const PAPER = [250, 250, 248];
const ATHL_DARK = [28, 95, 90];

mkdirSync(ASSETS, { recursive: true });

const outputs = [
  ['icon.png', makePng(1024, NIGHT, ATHL, 0.52)],
  ['adaptive-icon.png', makePng(1024, NIGHT, ATHL, 0.42)],
  ['splash.png', makePng(512, NIGHT, ATHL, 0.44)],
  ['favicon.png', makePng(48, PAPER, ATHL_DARK, 0.58)],
];

for (const [name, bytes] of outputs) {
  writeFileSync(join(ASSETS, name), bytes);
  process.stdout.write(`${name}  ${bytes.length} bytes\n`);
}
