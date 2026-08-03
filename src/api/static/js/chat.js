/**
 * RAG-Studio — Chat Page JavaScript
 * Vanilla JS, no frameworks.
 * Handles: session sidebar, SSE streaming, message rendering,
 *          citations, feedback, chat controls, i18n.
 *
 * Exposes: window.ChatApp
 */

(function () {
  'use strict';

  // ============================================================
  // State
  // ============================================================

  /** @type {Array<Object>} */
  let messages = [];
  /** @type {boolean} */
  let isStreaming = false;
  /** @type {AbortController|null} */
  let streamAbort = null;
  let streamSessionId = null;
  /** @type {number} */
  let streamRequestId = 0;
  /** @type {number} */
  let sessionLoadRequestId = 0;
  /** @type {Object.<string, Array<Object>>} */
  const knownMessagesBySession = Object.create(null);
  /** @type {number|null} */
  let streamRenderFrame = null;
  /** @type {string} */
  let pendingStreamingContent = '';
  /** @type {number} */
  let displayedStreamingLength = 0;
  const STREAM_RENDER_CODEPOINTS_PER_FRAME = 1;
  /** @type {HTMLElement|null} */
  let streamingNode = null;
  /** @type {boolean} */
  let userHasScrolledUp = false;
  /** @type {Map<string, string>} — messageId → 'positive' | 'negative' */
  const feedbackState = new Map();

  // ============================================================
  // Session State
  // ============================================================

  /** @type {string|null} */
  let activeSessionId = null;
  /** @type {Array<Object>} */
  let sessions = [];
  /** @type {string|null} */
  let contextMenuTargetId = null;
  const ACTIVE_SESSION_STORAGE_KEY = "rag-studio-active-session-id";
  const PENDING_USER_MESSAGE_STORAGE_KEY = "rag-studio-pending-user-message";


  // ============================================================
  // HTML Escape (AC-006.8)
  // ============================================================

  /**
   * Escape HTML special characters to prevent XSS.
   * Iterates characters — does NOT use regex.
   *
   * @param {string} str
   * @returns {string}
   */
  function escapeHtml(str) {
    let result = '';
    for (let i = 0; i < str.length; i++) {
      var ch = str[i];
      if (ch === '&') { result += '&amp;'; }
      else if (ch === '<') { result += '&lt;'; }
      else if (ch === '>') { result += '&gt;'; }
      else if (ch === '"') { result += '&quot;'; }
      else if (ch === "'") { result += '&#39;'; }
      else { result += ch; }
    }
    return result;
  }

  // ============================================================
  // i18n helper
  // ============================================================

  /** @param {string} key @returns {string} */
  function t(key) {
    if (window.RAGStudio && window.RAGStudio.translations && window.RAGStudio.translations[key]) {
      return window.RAGStudio.translations[key];
    }
    return key;
  }

  // ============================================================
  // DOM References
  // ============================================================

  function el(id) { return document.getElementById(id); }
  function rememberActiveSession(sessionId) {
    try {
      sessionStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
    } catch (error) {
      console.warn('Unable to remember active chat session.', error.name);
    }
  }

  function rememberedSessionId() {
    try {
      return sessionStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    } catch (error) {
      console.warn('Unable to restore active chat session.', error.name);
      return null;
    }
  }

  function rememberSessionSnapshot() {
    if (activeSessionId) rememberActiveSession(activeSessionId);
  }

  function restoredSessionSnapshot() {
    return rememberedSessionId();
  }

  function hydrateSessionSnapshot() {
    var sessionId = restoredSessionSnapshot();
    if (!sessionId) return false;
    activeSessionId = sessionId;
    if (el('sessionTitle')) {
      el('sessionTitle').textContent = 'Loading session...';
    }
    return true;
  }

  function clearSessionSnapshot() {
    try {
      sessionStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    } catch (error) {
      console.warn('Unable to clear cached chat session.', error.name);
    }
  }

  function rememberPendingUserMessage(sessionId, message) {
    try {
      sessionStorage.setItem(
        PENDING_USER_MESSAGE_STORAGE_KEY,
        JSON.stringify({
          session_id: sessionId,
          message_id: message.id,
          content: message.content,
          created_at: message.created_at
        })
      );
    } catch (error) {
      console.warn('Unable to remember pending user message.', error.name);
    }
  }

  function clearPendingUserMessage() {
    try {
      sessionStorage.removeItem(PENDING_USER_MESSAGE_STORAGE_KEY);
    } catch (error) {
      console.warn('Unable to clear pending user message.', error.name);
    }
  }

  function pendingUserMessage() {
    try {
      var serializedMessage = sessionStorage.getItem(PENDING_USER_MESSAGE_STORAGE_KEY);
      if (!serializedMessage) return null;
      var message = JSON.parse(serializedMessage);
      if (
        !message ||
        typeof message !== 'object' ||
        Array.isArray(message) ||
        typeof message.session_id !== 'string' ||
        !message.session_id ||
        typeof message.message_id !== 'string' ||
        !message.message_id ||
        typeof message.content !== 'string' ||
        !message.content ||
        typeof message.created_at !== 'string' ||
        !message.created_at
      ) {
        clearPendingUserMessage();
        return null;
      }
      return {
        session_id: message.session_id,
        message_id: message.message_id,
        content: message.content,
        created_at: message.created_at
      };
    } catch (error) {
      clearPendingUserMessage();
      return null;
    }
  }

  async function replayPendingUserMessage() {
    var message = pendingUserMessage();
    if (!message) return;
    try {
      await commitUserMessage(message.session_id, {
        id: message.message_id,
        content: message.content
      });
      clearPendingUserMessage();
    } catch (error) {
      console.warn('Unable to replay pending user message.', error.name);
    }
  }

  function sendPendingUserMessageBeacon() {
    var message = pendingUserMessage();
    if (!message || !navigator.sendBeacon) return;
    try {
      navigator.sendBeacon(
        '/api/chat/sessions/' + encodeURIComponent(message.session_id) + '/messages',
        new Blob(
          [JSON.stringify({ content: message.content, message_id: message.message_id })],
          { type: 'application/json' }
        )
      );
    } catch (error) {
      console.warn('Unable to send pending user message beacon.', error.name);
    }
  }

  function rememberMessagesForSession(sessionId, sessionMessages) {
    knownMessagesBySession[sessionId] = sessionMessages.slice();
  }

  function mergeMessagesForSession(sessionId, serverMessages) {
    var knownMessages = knownMessagesBySession[sessionId] || [];
    var mergedMessages = serverMessages.slice();
    var serverMessageIds = Object.create(null);
    mergedMessages.forEach(function (message) {
      serverMessageIds[message.id] = true;
    });
    knownMessages.forEach(function (message) {
      if (!serverMessageIds[message.id]) mergedMessages.push(message);
    });
    rememberMessagesForSession(sessionId, mergedMessages);
    return mergedMessages;
  }

  function createClientMessageId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return 'local-' + Date.now() + '-' + Math.random().toString(16).slice(2);
  }

  async function commitUserMessage(sessionId, message) {
    var response = await fetch(
      '/api/chat/sessions/' + encodeURIComponent(sessionId) + '/messages',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: message.content, message_id: message.id }),
        keepalive: true
      }
    );
    if (!response.ok) throw new Error(await responseErrorMessage(response));
  }

  // ============================================================
  // Message Sending (SSE Streaming)
  // ============================================================

  function isCurrentStream(requestId, sessionId) {
    return requestId === streamRequestId && (activeSessionId || 'default') === sessionId;
  }

  function setStreamingControls(active) {
    var sendButton = el('btnSend');
    var stopButton = el('btnStop');
    var input = el('chatInput');
    if (sendButton) sendButton.hidden = active;
    if (stopButton) stopButton.hidden = !active;
    if (input) input.disabled = active;
  }

  function removeStreamingMessage() {
    if (streamRenderFrame !== null) {
      cancelAnimationFrame(streamRenderFrame);
      streamRenderFrame = null;
    }
    pendingStreamingContent = '';
    displayedStreamingLength = 0;
    if (streamingNode) streamingNode.remove();
    streamingNode = null;
  }

  function detachActiveStream() {
    if (!streamAbort) return;
    var controller = streamAbort;
    streamAbort = null;
    streamSessionId = null;
    streamRequestId += 1;
    controller.abort();
    isStreaming = false;
    hideLoadingIndicator();
    removeStreamingMessage();
    setStreamingControls(false);
  }

  async function stopActiveStream() {
    var sessionId = streamSessionId || activeSessionId;
    detachActiveStream();
    if (!sessionId) return;
    try {
      var response = await fetch(
        '/api/chat/sessions/' + encodeURIComponent(sessionId) + '/cancel',
        { method: 'POST' }
      );
      if (!response.ok) throw new Error(await responseErrorMessage(response));
      showToast(t('chat_stream_cancelled') || 'Response stopped.');
    } catch (error) {
      console.error('stopActiveStream failed:', error.name || 'Error');
      showToast(t('chat_stream_failed') || 'The response could not be stopped.');
    }
  }

  function nextStreamingCodePointEnd(content, start) {
    var firstCodeUnit = content.charCodeAt(start);
    if (firstCodeUnit >= 0xD800 && firstCodeUnit <= 0xDBFF) {
      if (start + 1 >= content.length) return start;
      var secondCodeUnit = content.charCodeAt(start + 1);
      if (secondCodeUnit >= 0xDC00 && secondCodeUnit <= 0xDFFF) return start + 2;
    }
    return start + 1;
  }

  function scheduleStreamingRender(requestId, sessionId) {
    if (streamRenderFrame !== null) return;
    streamRenderFrame = requestAnimationFrame(function renderStreamingFrame() {
      streamRenderFrame = null;
      if (!isCurrentStream(requestId, sessionId)) return;
      if (!streamingNode) {
        streamingNode = document.createElement('div');
        streamingNode.className = 'message assistant streaming';
        streamingNode.dataset.requestId = String(requestId);
        var bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        streamingNode.appendChild(bubble);
        el('chatMessages').appendChild(streamingNode);
      }
      var madeProgress = false;
      for (var index = 0; index < STREAM_RENDER_CODEPOINTS_PER_FRAME; index += 1) {
        var nextLength = nextStreamingCodePointEnd(
          pendingStreamingContent,
          displayedStreamingLength
        );
        if (nextLength === displayedStreamingLength) break;
        displayedStreamingLength = nextLength;
        madeProgress = true;
      }
      if (madeProgress) {
        streamingNode.querySelector('.message-bubble').textContent =
          pendingStreamingContent.substring(0, displayedStreamingLength);
        scrollToBottom();
      }
      if (displayedStreamingLength < pendingStreamingContent.length && madeProgress) {
        scheduleStreamingRender(requestId, sessionId);
      }
    });
  }

  function updateStreamingMessage(content, requestId, sessionId) {
    if (!isCurrentStream(requestId, sessionId)) return;
    pendingStreamingContent = content;
    scheduleStreamingRender(requestId, sessionId);
  }

  function flushStreamingMessage(requestId, sessionId) {
    return new Promise(function (resolve) {
      var resolved = false;

      function finish() {
        if (resolved) return;
        resolved = true;
        document.removeEventListener('visibilitychange', finishWhenHidden);
        resolve();
      }

      function finishWhenHidden() {
        if (document.visibilityState === 'hidden') {
          displayedStreamingLength = pendingStreamingContent.length;
          finish();
        }
      }

      function checkRenderProgress() {
        if (resolved) return;
        if (!isCurrentStream(requestId, sessionId) || displayedStreamingLength >= pendingStreamingContent.length) {
          finish();
          return;
        }
        if (
          nextStreamingCodePointEnd(pendingStreamingContent, displayedStreamingLength) ===
          displayedStreamingLength
        ) {
          displayedStreamingLength = pendingStreamingContent.length;
          if (streamingNode) {
            streamingNode.querySelector('.message-bubble').textContent =
              pendingStreamingContent;
            scrollToBottom();
          }
          finish();
          return;
        }
        if (document.visibilityState === 'hidden') {
          finishWhenHidden();
          return;
        }
        scheduleStreamingRender(requestId, sessionId);
        requestAnimationFrame(checkRenderProgress);
      }

      document.addEventListener('visibilitychange', finishWhenHidden);
      checkRenderProgress();
    });
  }
  async function responseErrorMessage(response) {
    if (response.status === 409) {
      return t('chat_stream_conflict') || 'This chat already has a response in progress.';
    }
    if (response.status === 503) {
      var retryAfter = response.headers.get('Retry-After');
      var capacity = t('chat_stream_capacity') || 'Chat is busy. Please retry shortly.';
      return retryAfter ? capacity + ' (' + retryAfter + 's)' : capacity;
    }
    return t('chat_stream_failed') || 'The response could not be completed. Please retry.';
  }

  async function sendMessage(text) {
    if (!text.trim() || isStreaming) return;

    if (!activeSessionId) {
      await createSession();
      if (!activeSessionId) {
        showToast(t('chat_stream_failed') || 'Unable to create a chat session.');
        return;
      }
    }

    var requestSessionId = activeSessionId;
    var requestId = ++streamRequestId;
    var controller = new AbortController();
    streamAbort = controller;
    streamSessionId = requestSessionId;
    var userMsg = {
      id: createClientMessageId(),
      role: 'user',
      content: text,
      created_at: new Date().toISOString()
    };
    messages.push(userMsg);
    rememberMessagesForSession(requestSessionId, messages);
    rememberSessionSnapshot();
    renderMessages();
    updateEmptyState();
    el('chatInput').value = '';
    autoResizeTextarea();
    scrollToBottom();

    isStreaming = true;
    setStreamingControls(true);
    showLoadingIndicator();

    var assistantContent = '';
    var assistantMsgId = null;
    var citations = null;
    var completed = false;
    var streamFailure = null;

    try {
      rememberPendingUserMessage(requestSessionId, userMsg);
      await commitUserMessage(requestSessionId, userMsg);
      clearPendingUserMessage();
      if (!isCurrentStream(requestId, requestSessionId)) return;
      var resp = await fetch('/api/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: text,
          session_id: requestSessionId,
          message_id: userMsg.id
        }),
        signal: controller.signal
      });
      if (!resp.ok) {
        var responseError = new Error(await responseErrorMessage(resp));
        responseError.name = 'HttpResponseError';
        throw responseError;
      }
      if (!resp.body || !window.RAGSse) throw new Error('Streaming unavailable');

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var parser = new window.RAGSse.SseParser(function (frame) {
        if (!isCurrentStream(requestId, requestSessionId)) return;
        var data = frame.data || {};
        if (frame.event === 'token' && typeof data.token === 'string') {
          hideLoadingIndicator();
          assistantContent += data.token;
          assistantMsgId = data.message_id || assistantMsgId;
          updateStreamingMessage(assistantContent, requestId, requestSessionId);
        } else if (frame.event === 'done') {
          completed = true;
          assistantContent = data.full_response || assistantContent;
          assistantMsgId = data.message_id || assistantMsgId;
          citations = data.citations || null;
        } else if (frame.event === 'error') {
          streamFailure = new Error(
            data.message || t('chat_stream_failed') || 'The response could not be completed.'
          );
          streamFailure.name = 'StreamResponseError';
        }
      }, function () {
        streamFailure = new Error(t('chat_stream_failed') || 'Malformed stream response.');
        streamFailure.name = 'MalformedStreamError';
      });

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        parser.push(decoder.decode(chunk.value, { stream: true }));
        if (streamFailure) throw streamFailure;
      }
      parser.push(decoder.decode());
      parser.finish();
      if (streamFailure) throw streamFailure;
      if (!completed || !assistantMsgId) throw new Error('Incomplete stream');
      await flushStreamingMessage(requestId, requestSessionId);
      if (!isCurrentStream(requestId, requestSessionId)) return;

      if (!isCurrentStream(requestId, requestSessionId)) return;

      removeStreamingMessage();
      messages.push({
        id: assistantMsgId,
        role: 'assistant',
        content: assistantContent,
        created_at: new Date().toISOString(),
        citations: citations
      });
      rememberMessagesForSession(requestSessionId, messages);
      hideLoadingIndicator();
      renderMessages();
      scrollToBottom();
    } catch (error) {
      removeStreamingMessage();
      hideLoadingIndicator();
      if (error.name !== 'AbortError' && isCurrentStream(requestId, requestSessionId)) {
        console.error('sendMessage failed:', error.name || 'Error');
        showToast(error.message || t('chat_stream_failed') || 'Response failed.');
      }
    } finally {
      if (requestId === streamRequestId) {
        streamAbort = null;
        streamSessionId = null;
        isStreaming = false;
        setStreamingControls(false);
        if (el('chatInput')) el('chatInput').focus();
        rememberSessionSnapshot();
      }
    }
  }

  async function reloadSessionMessages(sessionId, requestId) {
    var response = await fetch(
      '/api/chat/sessions/' + encodeURIComponent(sessionId) + '/messages'
    );
    if (!response.ok || !isCurrentStream(requestId, sessionId)) return;
    messages = mergeMessagesForSession(sessionId, await response.json());
    renderMessages();
    updateEmptyState();
    scrollToBottom();
  }

  async function reattachSessionStream(sessionId) {
    if (isStreaming && streamSessionId === sessionId) return;
    detachActiveStream();
    var requestId = ++streamRequestId;
    var controller = new AbortController();
    streamAbort = controller;
    streamSessionId = sessionId;
    isStreaming = true;
    setStreamingControls(true);
    showLoadingIndicator();
    var assistantContent = '';
    var completed = false;
    var streamFailure = null;

    try {
      var response = await fetch(
        '/api/chat/sessions/' + encodeURIComponent(sessionId) + '/stream',
        { signal: controller.signal }
      );
      if (response.status === 404) {
        await reloadSessionMessages(sessionId, requestId);
        return;
      }
      if (!response.ok) throw new Error(await responseErrorMessage(response));
      if (!response.body || !window.RAGSse) throw new Error('Streaming unavailable');

      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var parser = new window.RAGSse.SseParser(function (frame) {
        if (!isCurrentStream(requestId, sessionId)) return;
        var data = frame.data || {};
        if (frame.event === 'token' && typeof data.token === 'string') {
          hideLoadingIndicator();
          assistantContent += data.token;
          updateStreamingMessage(assistantContent, requestId, sessionId);
        } else if (frame.event === 'done') {
          completed = true;
          assistantContent = data.full_response || assistantContent;
        } else if (frame.event === 'error') {
          streamFailure = new Error(
            data.message || t('chat_stream_failed') || 'The response could not be completed.'
          );
        }
      }, function () {
        streamFailure = new Error(t('chat_stream_failed') || 'Malformed stream response.');
      });

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        parser.push(decoder.decode(chunk.value, { stream: true }));
        if (streamFailure) throw streamFailure;
      }
      parser.push(decoder.decode());
      parser.finish();
      if (streamFailure) throw streamFailure;
      if (!completed) throw new Error('Incomplete stream');
      await flushStreamingMessage(requestId, sessionId);
      if (!isCurrentStream(requestId, sessionId)) return;
      removeStreamingMessage();
      await reloadSessionMessages(sessionId, requestId);
    } catch (error) {
      if (error.name !== 'AbortError' && isCurrentStream(requestId, sessionId)) {
        console.error('reattachSessionStream failed:', error.name || 'Error');
        showToast(error.message || t('chat_stream_failed') || 'Response failed.');
      }
    } finally {
      if (requestId === streamRequestId) {
        streamAbort = null;
        streamSessionId = null;
        isStreaming = false;
        hideLoadingIndicator();
        setStreamingControls(false);
      }
    }
  }

  function showLoadingIndicator() {
    var msgs = el('chatMessages');
    var loader = document.createElement('div');
    loader.className = 'message assistant';
    loader.id = '_loadingIndicator';
    loader.innerHTML = '<div class="message-bubble"><div class="loading-dots"><span></span><span></span><span></span></div></div>';
    msgs.appendChild(loader);
    scrollToBottom();
  }

  function hideLoadingIndicator() {
    var loader = document.getElementById('_loadingIndicator');
    if (loader) loader.remove();
  }

  // ============================================================
  // Message Rendering
  // ============================================================

  function renderMessages() {
    var container = el('chatMessages');
    // Remove all message elements
    var msgEls = container.querySelectorAll('.message');
    msgEls.forEach(function (el) { el.remove(); });
    // Remove empty state
    var empty = container.querySelector('.chat-empty-state');
    if (empty) empty.style.display = messages.length === 0 ? '' : 'none';

    messages.forEach(function (msg) {
      var div = document.createElement('div');
      div.className = 'message ' + msg.role + (msg.id === '_streaming' ? ' streaming' : '');
      div.dataset.messageId = msg.id;

      var bubble = document.createElement('div');
      bubble.className = 'message-bubble';

      // Parse citations in content: replace [N] with clickable badges
      var contentHtml = escapeHtml(msg.content);
      contentHtml = contentHtml.replace(/\[(\d+)\]/g, function (match, num) {
        return '<span class="citation-badge" data-citation-index="' + num + '">[' + num + ']</span>';
      });

      bubble.innerHTML = contentHtml;

      // Feedback buttons for assistant messages
      if (msg.role === 'assistant' && msg.id !== '_streaming') {
        var feedbackDiv = document.createElement('div');
        feedbackDiv.className = 'feedback-buttons';

        var currentFeedback = feedbackState.get(msg.id) || null;

        var likeBtn = document.createElement('button');
        likeBtn.className = 'feedback-btn like' + (currentFeedback === 'positive' ? ' active' : '');
        likeBtn.setAttribute('aria-label', 'Like');
        likeBtn.textContent = '\uD83D\uDC4D';
        likeBtn.addEventListener('click', function () {
          feedbackState.set(msg.id, 'positive');
          submitFeedback(msg.id, 'positive');
          // Update visual state immediately
          var parent = likeBtn.parentNode;
          if (parent) {
            var dislikeBtn = parent.querySelector('.dislike');
            if (dislikeBtn) dislikeBtn.classList.remove('active');
            likeBtn.classList.add('active');
          }
        });

        var dislikeBtn = document.createElement('button');
        dislikeBtn.className = 'feedback-btn dislike' + (currentFeedback === 'negative' ? ' active' : '');
        dislikeBtn.setAttribute('aria-label', 'Dislike');
        dislikeBtn.textContent = '\uD83D\uDC4E';
        dislikeBtn.addEventListener('click', function () {
          feedbackState.set(msg.id, 'negative');
          submitFeedback(msg.id, 'negative');
          // Update visual state immediately
          var parent = dislikeBtn.parentNode;
          if (parent) {
            var likeBtnEl = parent.querySelector('.like');
            if (likeBtnEl) likeBtnEl.classList.remove('active');
            dislikeBtn.classList.add('active');
          }
        });

        var copyBtn = document.createElement('button');
        copyBtn.className = 'feedback-btn copy';
        copyBtn.setAttribute('aria-label', 'Copy message');
        copyBtn.textContent = '\uD83D\uDCCB';
        copyBtn.addEventListener('click', function () {
          copyMessageContent(msg.content);
        });

        feedbackDiv.appendChild(likeBtn);
        feedbackDiv.appendChild(dislikeBtn);
        feedbackDiv.appendChild(copyBtn);
        bubble.appendChild(feedbackDiv);
      }

      // Citations expandable card
      if (msg.citations && msg.citations.length > 0) {
        var citeDiv = document.createElement('div');
        citeDiv.className = 'citation-card';
        msg.citations.forEach(function (c) {
          var citeItem = document.createElement('div');
          citeItem.className = 'citation-item';
          citeItem.dataset.citationIndex = c.index;
          citeItem.style.display = 'none';
          citeItem.innerHTML =
            '<div class="citation-header">' +
            '<span class="citation-filename">' + escapeHtml(c.filename) + '</span>' +
            '<span class="citation-score">Score: ' + (c.score ? c.score.toFixed(2) : 'N/A') + '</span>' +
            '</div>' +
            '<div class="citation-text">' + escapeHtml(truncateText(c.chunk_text || '', 200)) + '</div>' +
            '<button class="citation-toggle" data-expanded="false">' + t('chat_citation_show_more') + '</button>';
          citeItem.querySelector('.citation-toggle').addEventListener('click', function (e) {
            e.stopPropagation();
            var textEl = citeItem.querySelector('.citation-text');
            var btn = e.target;
            var isExpanded = btn.dataset.expanded === 'true';
            if (isExpanded) {
              textEl.textContent = truncateText(c.chunk_text || '', 200);
              btn.textContent = t('chat_citation_show_more');
              btn.dataset.expanded = 'false';
            } else {
              textEl.textContent = c.chunk_text || '';
              btn.textContent = t('chat_citation_show_less');
              btn.dataset.expanded = 'true';
            }
          });
          citeDiv.appendChild(citeItem);
        });
        bubble.appendChild(citeDiv);
      }

      div.appendChild(bubble);
      container.appendChild(div);
    });

    // Bind citation badge clicks and hovers
    container.querySelectorAll('.citation-badge').forEach(function (badge) {
      // Click: toggle citation card visibility
      badge.addEventListener('click', function () {
        var index = badge.dataset.citationIndex;
        var citeItem = container.querySelector('.citation-item[data-citation-index="' + index + '"]');
        if (citeItem) {
          citeItem.style.display = citeItem.style.display === 'none' ? 'block' : 'none';
        }
      });

      // Hover: show tooltip
      badge.addEventListener('mouseenter', function (e) {
        var index = badge.dataset.citationIndex;
        // Find the parent message element to get citations
        var messageEl = badge.closest('.message');
        var msgId = messageEl ? messageEl.dataset.messageId : null;
        if (!msgId) return;

        // Look up citation data from the messages array
        var msg = null;
        for (var m = 0; m < messages.length; m++) {
          if (messages[m].id === msgId) {
            msg = messages[m];
            break;
          }
        }
        if (!msg || !msg.citations) return;

        var citation = null;
        for (var c = 0; c < msg.citations.length; c++) {
          if (String(msg.citations[c].index) === String(index)) {
            citation = msg.citations[c];
            break;
          }
        }
        if (!citation) return;

        // Remove any existing tooltip
        var existing = document.querySelector('.citation-tooltip');
        if (existing) existing.remove();

        // Create tooltip
        var tooltip = document.createElement('div');
        tooltip.className = 'citation-tooltip';
        var chunkText = citation.chunk_text || '';
        var truncated = chunkText.length > 200 ? chunkText.substring(0, 200) + '...' : chunkText;
        var scoreText = citation.score ? 'Score: ' + Number(citation.score).toFixed(2) : '';

        tooltip.innerHTML =
          '<div class="citation-tooltip-filename">' + escapeHtml(citation.filename || 'Unknown') + '</div>' +
          '<div class="citation-tooltip-text">' + escapeHtml(truncated) + '</div>' +
          '<div class="citation-tooltip-score">' + escapeHtml(scoreText) + '</div>';

        document.body.appendChild(tooltip);

        // Position tooltip relative to the badge
        var rect = badge.getBoundingClientRect();
        var tooltipWidth = tooltip.offsetWidth;
        var tooltipHeight = tooltip.offsetHeight;
        var left = rect.left + rect.width / 2 - tooltipWidth / 2;
        var top = rect.top - tooltipHeight - 8;

        // Clamp horizontally
        left = Math.max(8, Math.min(left, window.innerWidth - tooltipWidth - 8));

        // If tooltip would overflow above viewport, show below the badge
        if (top < 8) {
          top = rect.bottom + 8;
          tooltip.classList.add('tooltip-above');
        }

        tooltip.style.left = left + 'px';
        tooltip.style.top = top + 'px';
      });

      badge.addEventListener('mouseleave', function () {
        var tooltip = document.querySelector('.citation-tooltip');
        if (tooltip) tooltip.remove();
      });
    });
  }

  /** @param {string} text @param {number} maxLen @returns {string} */
  function truncateText(text, maxLen) {
    if (text.length <= maxLen) return text;
    return text.substring(0, maxLen) + '...';
  }

  function updateEmptyState() {
    var emptyState = el('chatEmptyState');
    if (emptyState) {
      emptyState.style.display = messages.length === 0 ? '' : 'none';
    }
  }

  // ============================================================
  // Citations
  // ============================================================

  // Citation expansion is handled inline in renderMessages()

  // ============================================================
  // Feedback
  // ============================================================

  async function submitFeedback(messageId, feedback) {
    if (feedback === 'negative') {
      showFeedbackReasonDialog(function (reason) {
        doSubmitFeedback(messageId, feedback, reason);
      });
    } else {
      doSubmitFeedback(messageId, feedback, null);
    }
  }

  async function doSubmitFeedback(messageId, feedback, reason) {
    try {
      var resp = await fetch('/api/chat/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: activeSessionId || 'default',
          message_id: messageId,
          feedback: feedback,
          reason: reason || null
        })
      });
      if (resp.ok) {
        showToast(t('chat_feedback_thanks'));
      } else {
        // Revert feedback state on failure
        feedbackState.delete(messageId);
        renderMessages();
      }
    } catch (e) {
      console.error('submitFeedback error:', e);
      // Revert feedback state on error
      feedbackState.delete(messageId);
      renderMessages();
    }
  }

  function showFeedbackReasonDialog(onSubmit) {
    var dialog = el('feedbackReasonDialog');
    var input = el('feedbackReasonInput');
    input.value = '';
    dialog.style.display = 'flex';

    el('feedbackReasonSubmit').onclick = function () {
      dialog.style.display = 'none';
      if (onSubmit) onSubmit(input.value || null);
    };
    el('feedbackReasonCancel').onclick = function () {
      dialog.style.display = 'none';
      if (onSubmit) onSubmit(null);
    };
  }

  // ============================================================
  // Toast
  // ============================================================

  function showToast(message) {
    var toast = document.createElement('div');
    toast.className = 'chat-toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function () {
      toast.classList.add('chat-toast-fade-out');
      setTimeout(function () { toast.remove(); }, 300);
    }, 2000);
  }

  // ============================================================
  // Chat Controls
  // ============================================================

  function clearChat() {
    showConfirm(
      t('chat_clear_confirm') || 'Clear all messages?',
      async function () {
        detachActiveStream();
        if (activeSessionId) {
          try {
            var response = await fetch('/api/chat/sessions/' + encodeURIComponent(activeSessionId) + '/messages', {
              method: 'DELETE'
            });
            if (!response.ok) return;
          } catch (e) {
            console.error('clearChat error:', e);
            return;
          }
        }
        messages = [];
        if (activeSessionId) delete knownMessagesBySession[activeSessionId];
        renderMessages();
        updateEmptyState();
        scrollToBottom();
      }
    );
  }

  function regenerateLast() {
    if (isStreaming) return;
    // Find last user message
    var userMsgs = messages.filter(function (m) { return m.role === 'user'; });
    if (userMsgs.length === 0) return;
    var lastUser = userMsgs[userMsgs.length - 1];
    // Remove last assistant message if present
    var lastIdx = messages.length - 1;
    if (lastIdx >= 0 && messages[lastIdx].role === 'assistant') {
      messages.pop();
    }
    renderMessages();
    updateEmptyState();
    sendMessage(lastUser.content);
  }

  function copyMessageContent(content) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(content).then(function () {
        showToast(t('chat_copy_done'));
      });
    } else {
      // Fallback
      var ta = document.createElement('textarea');
      ta.value = content;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
      showToast(t('chat_copy_done'));
    }
  }

  // ============================================================
  // Auto-scroll
  // ============================================================

  function scrollToBottom() {
    if (userHasScrolledUp) return;
    var container = el('chatMessages');
    if (container) {
      requestAnimationFrame(function () {
        container.scrollTop = container.scrollHeight;
      });
    }
  }

  function trackScroll() {
    var container = el('chatMessages');
    if (!container) return;
    var threshold = 80;
    userHasScrolledUp = (container.scrollTop + container.clientHeight < container.scrollHeight - threshold);
  }

  // ============================================================
  // Textarea Auto-resize
  // ============================================================

  function autoResizeTextarea() {
    var textarea = el('chatInput');
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
  }

  // ============================================================
  // Event Binding
  // ============================================================

  function bindEvents() {
    // Chat form submit
    var chatForm = el('chatForm');
    if (chatForm) {
      chatForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var input = el('chatInput');
        if (input && input.value.trim()) {
          sendMessage(input.value.trim());
        }
      });
    }

    // Enter to send, Shift+Enter for newline
    var chatInput = el('chatInput');
    if (chatInput) {
      chatInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          if (this.value.trim()) {
            sendMessage(this.value.trim());
          }
        }
      });
      chatInput.addEventListener('input', autoResizeTextarea);
    }

    // Clear chat button
    var btnClear = el('btnClearChat');
    if (btnClear) btnClear.addEventListener('click', clearChat);

    // Regenerate button
    var btnRegenerate = el('btnRegenerate');
    if (btnRegenerate) btnRegenerate.addEventListener('click', regenerateLast);

    var btnStop = el('btnStop');
    if (btnStop) {
      btnStop.addEventListener('click', stopActiveStream);
    }

    // Scroll tracking
    var chatMessages = el('chatMessages');
    if (chatMessages) {
      chatMessages.addEventListener('scroll', trackScroll);
    }

    // Close modals on overlay click
    document.querySelectorAll('.modal-overlay').forEach(function (overlay) {
      overlay.addEventListener('click', function (e) {
        if (e.target === overlay) {
          overlay.style.display = 'none';
        }
      });
    });

    // Sidebar toggle
    var sidebarToggle = el('sidebarToggle');
    if (sidebarToggle) {
      sidebarToggle.addEventListener('click', function () {
        var sidebar = el('chatSidebar');
        var backdrop = el('sidebarBackdrop');
        var isCollapsed;
        if (sidebar) {
          sidebar.classList.toggle('collapsed');
          isCollapsed = sidebar.classList.contains('collapsed');
        }
        if (backdrop) {
          // Show backdrop only when sidebar is open (not collapsed)
          if (isCollapsed) {
            backdrop.classList.remove('visible');
          } else {
            backdrop.classList.add('visible');
          }
        }
      });
    }

    // Backdrop click closes sidebar
    var backdrop = el('sidebarBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', function () {
        var sidebar = el('chatSidebar');
        if (sidebar) sidebar.classList.add('collapsed');
        backdrop.classList.remove('visible');
      });
    }

    // New Chat button
    var btnNewChat = el('btnNewChat');
    if (btnNewChat) {
      btnNewChat.addEventListener('click', createSession);
    }

    // Context menu actions
    var contextMenu = el('contextMenu');
    if (contextMenu) {
      contextMenu.querySelectorAll('.context-menu-item').forEach(function (item) {
        item.addEventListener('click', function () {
          handleContextAction(item.dataset.action);
        });
      });
    }

    // Close context menu on scroll
    window.addEventListener('scroll', closeContextMenu, { passive: true });

    // Confirm dialog cancel
    var confirmCancel = el('confirmCancel');
    if (confirmCancel) {
      confirmCancel.addEventListener('click', function () {
        var dialog = el('confirmDialog');
        if (dialog) dialog.style.display = 'none';
      });
    }

    // Global Escape key — close rename dialog if open
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        var renameDialog = el('renameDialog');
        if (renameDialog && renameDialog.style.display === 'flex') {
          renameDialog.style.display = 'none';
          var renameInput = el('renameInput');
          if (renameInput) renameInput.value = '';
        }
      }
    });

    // Sidebar toggle on mobile: close sidebar when switching sessions
    el('sessionList') && el('sessionList').addEventListener('click', function () {
      // Close sidebar on mobile after selection
      if (window.innerWidth <= 1023) {
        var sidebar = el('chatSidebar');
        var backdrop = el('sidebarBackdrop');
        if (sidebar) sidebar.classList.add('collapsed');
        if (backdrop) backdrop.classList.remove('visible');
      }
    });
  }

  // ============================================================
  // Session Management
  // ============================================================

  async function loadSessions() {
    try {
      var resp = await fetch('/api/chat/sessions');
      if (!resp.ok) return false;
      sessions = await resp.json();
      renderSessionList();
      rememberSessionSnapshot();
      return true;
    } catch (e) {
      console.error('loadSessions error:', e);
      return false;
    }
  }
  async function createSession() {
    detachActiveStream();
    try {
      var resp = await fetch('/api/chat/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Session' })
      });
      if (!resp.ok) return;
      var session = await resp.json();
      sessions.unshift(session);
      renderSessionList();
      await switchToSession(session.id);
    } catch (e) {
      console.error('createSession error:', e);
    }
  }

  async function deleteSession(id) {
    if (activeSessionId === id) detachActiveStream();
    try {
      var resp = await fetch('/api/chat/sessions/' + encodeURIComponent(id), {
        method: 'DELETE'
      });
      if (!resp.ok) return;
      sessions = sessions.filter(function (s) { return s.id !== id; });
      delete knownMessagesBySession[id];
      if (activeSessionId === id) {
        activeSessionId = null;
        messages = [];
        clearSessionSnapshot();
        renderMessages();
        updateEmptyState();
        if (el('sessionTitle')) {
          el('sessionTitle').textContent = t('chat_new_session') || 'New Session';
        }
      }
      renderSessionList();
      rememberSessionSnapshot();
    } catch (e) {
      console.error('deleteSession error:', e);
    }
  }

  async function renameSession(id) {
    // Find current session title for pre-fill
    var currentSession = sessions.find(function (s) { return s.id === id; });
    var currentTitle = (currentSession && currentSession.title) ? currentSession.title : '';

    showRenameModal(currentTitle, async function (newTitle) {
      if (!newTitle || !newTitle.trim()) return;
      try {
        var resp = await fetch('/api/chat/sessions/' + encodeURIComponent(id), {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newTitle.trim() })
        });
        if (!resp.ok) return;
        var updated = await resp.json();
        sessions = sessions.map(function (s) {
          return s.id === id ? updated : s;
        });
        renderSessionList();
        rememberSessionSnapshot();
        if (activeSessionId === id && el('sessionTitle')) {
          el('sessionTitle').textContent = updated.title;
        }
      } catch (e) {
        console.error('renameSession error:', e);
      }
    });
  }

  function renderSessionList() {
    var list = el('sessionList');
    if (!list) return;
    list.innerHTML = '';

    if (sessions.length === 0) {
      var emptyDiv = document.createElement('div');
      emptyDiv.className = 'session-empty-state';
      emptyDiv.setAttribute('data-i18n', 'chat_no_sessions');
      emptyDiv.textContent = t('chat_no_sessions') || 'No sessions yet. Create your first chat.';
      list.appendChild(emptyDiv);
      return;
    }

    sessions.forEach(function (session) {
      // Skip auto-created "default" session — only user-created sessions appear
      if (session.id === 'default') return;
      var item = document.createElement('div');
      item.className = 'session-item' + (session.id === activeSessionId ? ' active' : '');
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', session.id === activeSessionId ? 'true' : 'false');
      item.dataset.sessionId = session.id;

      var title = document.createElement('span');
      title.className = 'session-item-title';
      title.textContent = session.title || 'New Session';

      var msgCount = session.message_count;
      var count = document.createElement('span');
      count.className = 'session-item-count';
      count.textContent = (typeof msgCount === 'number' && msgCount > 0) ? String(msgCount) : '';

      var menuBtn = document.createElement('button');
      menuBtn.className = 'session-menu-btn';
      menuBtn.textContent = '⋮';
      menuBtn.setAttribute('aria-label', 'Session menu');
      menuBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        showContextMenu(e, session.id);
      });

      item.appendChild(title);
      item.appendChild(count);
      item.appendChild(menuBtn);

      item.addEventListener('click', function () {
        switchToSession(session.id);
      });

      list.appendChild(item);
    });
  }

  async function switchToSession(id) {
    if (activeSessionId) rememberMessagesForSession(activeSessionId, messages);
    if (id !== activeSessionId) detachActiveStream();
    activeSessionId = id;
    rememberActiveSession(id);
    var loadRequestId = ++sessionLoadRequestId;
    // Update session title in header
    var session = sessions.find(function (s) { return s.id === id; });
    if (el('sessionTitle')) {
      el('sessionTitle').textContent = session ? session.title : 'New Session';
    }

    // Load messages for this session
    try {
      var resp = await fetch('/api/chat/sessions/' + encodeURIComponent(id) + '/messages');
      if (activeSessionId !== id || loadRequestId !== sessionLoadRequestId) return;
      if (resp.ok) {
        var msgs = await resp.json();
        messages = mergeMessagesForSession(id, msgs);
      } else {
        messages = mergeMessagesForSession(id, []);
      }
    } catch (e) {
      if (activeSessionId !== id || loadRequestId !== sessionLoadRequestId) return;
      messages = mergeMessagesForSession(id, []);
    }
    renderMessages();
    updateEmptyState();
    renderSessionList();
    scrollToBottom();
    rememberSessionSnapshot();
    await reattachSessionStream(id);
  }

  function showContextMenu(e, sessionId) {
    e.preventDefault();
    contextMenuTargetId = sessionId;
    var menu = el('contextMenu');
    if (!menu) return;

    // Position the menu near the click
    menu.style.display = 'block';
    menu.style.position = 'fixed';
    menu.style.zIndex = '300';
    menu.style.left = Math.min(e.clientX, window.innerWidth - 180) + 'px';
    menu.style.top = Math.min(e.clientY, window.innerHeight - 120) + 'px';

    // Close on outside click
    setTimeout(function () {
      document.addEventListener('click', closeContextMenu, { once: true });
    }, 0);
  }

  function closeContextMenu() {
    var menu = el('contextMenu');
    if (menu) menu.style.display = 'none';
    contextMenuTargetId = null;
  }

  function handleContextAction(action) {
    // Capture ID BEFORE closeContextMenu which nullifies it
    var id = contextMenuTargetId;
    closeContextMenu();
    if (!id) return;
    switch (action) {
      case 'rename':
        renameSession(id);
        break;
      case 'delete':
        showConfirm(
          t('chat_delete_confirm') || 'Delete this session?',
          function () { deleteSession(id); }
        );
        break;
    }
  }

  function showRenameModal(currentTitle, callback) {
    var dialog = el('renameDialog');
    var input = el('renameInput');
    if (!dialog || !input) return;

    input.value = currentTitle;
    dialog.style.display = 'flex';
    input.focus();
    // Select all text for easy replacement
    input.select();

    function close() {
      dialog.style.display = 'none';
      input.value = '';
    }

    function submit() {
      var newTitle = input.value;
      close();
      if (callback) callback(newTitle);
    }

    el('renameOk').onclick = submit;
    el('renameCancel').onclick = close;

    // Keyboard: Enter in input triggers OK
    input.onkeydown = function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        submit();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        close();
      }
    };
  }

  function showConfirm(message, onOk) {
    var dialog = el('confirmDialog');
    var msgEl = el('confirmMessage');
    if (!dialog || !msgEl) return;
    msgEl.textContent = message;
    dialog.style.display = 'flex';

    el('confirmOk').onclick = function () {
      dialog.style.display = 'none';
      if (onOk) onOk();
    };
    el('confirmCancel').onclick = function () {
      dialog.style.display = 'none';
    };
  }

  // ============================================================
  // Initialization
  // ============================================================

  async function init() {
    var hydratedSession = hydrateSessionSnapshot();
    bindEvents();
    updateEmptyState();
    window.addEventListener('pagehide', function () {
      rememberSessionSnapshot();
      detachActiveStream();
      sendPendingUserMessageBeacon();
    });
    var sessionsLoaded = await loadSessions();
    if (!sessionsLoaded) return;
    await replayPendingUserMessage();
    var restoredSessionId = rememberedSessionId();
    if (restoredSessionId && sessions.some(function (session) { return session.id === restoredSessionId; })) {
      await switchToSession(restoredSessionId);
    } else if (hydratedSession) {
      activeSessionId = null;
      messages = [];
      clearSessionSnapshot();
      if (el('sessionTitle')) el('sessionTitle').textContent = t('chat_new_session') || 'New Session';
      renderMessages();
      updateEmptyState();
      renderSessionList();
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  window.addEventListener('ragstudio:locale-changed', renderSessionList);

  // ============================================================
  // Public API
  // ============================================================

  window.ChatApp = {
    sendMessage: sendMessage,
    clearChat: clearChat,
    regenerateLast: regenerateLast,
    getMessages: function () { return messages; },
    isStreaming: function () { return isStreaming; },
    loadSessions: loadSessions,
    createSession: createSession,
    deleteSession: deleteSession,
    renameSession: renameSession,
    detachActiveStream: detachActiveStream,
    stopActiveStream: stopActiveStream,
    reattachSessionStream: reattachSessionStream,
    getActiveSessionId: function () { return activeSessionId; },
    getSessions: function () { return sessions; }
  };
})();
