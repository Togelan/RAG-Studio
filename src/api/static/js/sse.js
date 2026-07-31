/** Frame-safe Server-Sent Events parser for streamed chat responses. */
(function (global) {
  'use strict';

  function SseParser(onEvent, onMalformed) {
    this.buffer = '';
    this.onEvent = onEvent;
    this.onMalformed = onMalformed || function () {};
  }

  SseParser.prototype.push = function (text) {
    this.buffer += text;
    var boundary;
    while ((boundary = this.buffer.search(/\r?\n\r?\n/)) !== -1) {
      var separator = this.buffer.slice(boundary).match(/^\r?\n\r?\n/)[0];
      var frame = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + separator.length);
      this._dispatch(frame);
    }
  };

  SseParser.prototype.finish = function () {
    if (this.buffer.trim()) this._dispatch(this.buffer);
    this.buffer = '';
  };

  SseParser.prototype._dispatch = function (frame) {
    if (!frame || frame.charAt(0) === ':') return;
    var eventName = 'message';
    var dataLines = [];
    frame.split(/\r?\n/).forEach(function (line) {
      if (line.indexOf('event:') === 0) {
        eventName = line.slice(6).trim() || 'message';
      } else if (line.indexOf('data:') === 0) {
        dataLines.push(line.slice(5).replace(/^ /, ''));
      }
    });
    if (dataLines.length === 0) return;
    try {
      this.onEvent({ event: eventName, data: JSON.parse(dataLines.join('\n')) });
    } catch (error) {
      this.onMalformed({ event: eventName, error: error });
    }
  };

  global.RAGSse = { SseParser: SseParser };
})(typeof window !== 'undefined' ? window : globalThis);
