import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('src/api/static/js/sse.js', 'utf8');
const context = { window: {} };
vm.runInNewContext(source, context, { filename: 'sse.js' });

const events = [];
const malformed = [];
const parser = new context.window.RAGSse.SseParser(
  (event) => events.push(event),
  (event) => malformed.push(event)
);
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const payload = [
  'event: token\r\ndata: {"token":"Привет 🌿"}\r\n\r\n',
  ': heartbeat\n\n',
  'event: done\ndata: {"done":true,"full_response":"Привет 🌿"}\n\n',
  'event: token\ndata: {bad json}\n\n'
].join('');
const bytes = encoder.encode(payload);

for (const [start, end] of [[0, 7], [7, 21], [21, 37], [37, 52], [52, 71], [71, bytes.length]]) {
  parser.push(decoder.decode(bytes.slice(start, end), { stream: end !== bytes.length }));
}
parser.push(decoder.decode());
parser.finish();

assert.equal(events.length, 2);
assert.equal(events[0].event, 'token');
assert.equal(events[0].data.token, 'Привет 🌿');
assert.equal(events[1].event, 'done');
assert.equal(events[1].data.full_response, 'Привет 🌿');
assert.equal(malformed.length, 1);
console.log('SSE parser: fragmented UTF-8/CRLF and malformed-frame checks passed');
