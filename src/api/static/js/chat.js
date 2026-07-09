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

  // ============================================================
  // Message Sending (SSE Streaming)
  // ============================================================

  async function sendMessage(text) {
    if (!text.trim() || isStreaming) return;

    // Add user message locally
    var userMsg = {
      id: 'local-' + Date.now(),
      role: 'user',
      content: text,
      created_at: new Date().toISOString()
    };
    messages.push(userMsg);
    renderMessages();
    updateEmptyState();
    el('chatInput').value = '';
    autoResizeTextarea();
    scrollToBottom();

    // Start streaming
    isStreaming = true;
    el('btnSend').disabled = true;
    showLoadingIndicator();

    try {
      var resp = await fetch('/api/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text, session_id: activeSessionId || 'default' })
      });
      if (!resp.ok) throw new Error('Message send failed');

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var assistantContent = '';
      var assistantMsgId = null;
      var citations = null;
      var firstToken = true;

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        var chunkStr = decoder.decode(chunk.value, { stream: true });
        var lines = chunkStr.split('\n');

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i].trim();
          if (!line.startsWith('data: ')) continue;
          var jsonStr = line.substring(6);
          try {
            var data = JSON.parse(jsonStr);
            if (data.token) {
              if (firstToken) {
                hideLoadingIndicator();
                firstToken = false;
              }
              assistantContent += data.token;
              assistantMsgId = data.message_id;
              // Update or create assistant bubble
              updateStreamingMessage(assistantContent, assistantMsgId);
            }
            if (data.done) {
              assistantContent = data.full_response || assistantContent;
              assistantMsgId = data.message_id || assistantMsgId;
              citations = data.citations || null;
            }
          } catch (parseErr) {
            // Skip unparseable lines
          }
        }
      }

      // Finalize assistant message
      if (assistantMsgId) {
        messages = messages.filter(function (m) { return m.id !== '_streaming'; });
        messages.push({
          id: assistantMsgId,
          role: 'assistant',
          content: assistantContent,
          created_at: new Date().toISOString(),
          citations: citations
        });
      }

      hideLoadingIndicator();
      renderMessages();
      scrollToBottom();

    } catch (e) {
      console.error('sendMessage error:', e);
      hideLoadingIndicator();
    } finally {
      isStreaming = false;
      el('btnSend').disabled = false;
      el('chatInput').focus();
    }
  }

  function updateStreamingMessage(content, msgId) {
    // Remove any previous streaming placeholder
    messages = messages.filter(function (m) { return m.id !== '_streaming'; });
    messages.push({
      id: '_streaming',
      role: 'assistant',
      content: content,
      created_at: new Date().toISOString(),
      citations: null
    });
    renderMessages();
    scrollToBottom();
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
        if (activeSessionId) {
          try {
            await fetch('/api/chat/sessions/' + encodeURIComponent(activeSessionId) + '/messages', {
              method: 'DELETE'
            });
          } catch (e) {
            console.error('clearChat error:', e);
          }
        }
        messages = [];
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
      if (!resp.ok) return;
      sessions = await resp.json();
      renderSessionList();
    } catch (e) {
      console.error('loadSessions error:', e);
    }
  }

  async function createSession() {
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
      switchToSession(session.id);
    } catch (e) {
      console.error('createSession error:', e);
    }
  }

  async function deleteSession(id) {
    try {
      var resp = await fetch('/api/chat/sessions/' + encodeURIComponent(id), {
        method: 'DELETE'
      });
      if (!resp.ok) return;
      sessions = sessions.filter(function (s) { return s.id !== id; });
      if (activeSessionId === id) {
        activeSessionId = null;
        messages = [];
        renderMessages();
        updateEmptyState();
        if (el('sessionTitle')) {
          el('sessionTitle').textContent = t('chat_new_session') || 'New Session';
        }
      }
      renderSessionList();
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
      emptyDiv.textContent = 'No sessions yet. Create your first chat.';
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
    activeSessionId = id;
    // Update session title in header
    var session = sessions.find(function (s) { return s.id === id; });
    if (el('sessionTitle')) {
      el('sessionTitle').textContent = session ? session.title : 'New Session';
    }

    // Load messages for this session
    try {
      var resp = await fetch('/api/chat/sessions/' + encodeURIComponent(id) + '/messages');
      if (resp.ok) {
        var msgs = await resp.json();
        messages = msgs;
      } else {
        messages = [];
      }
    } catch (e) {
      messages = [];
    }
    renderMessages();
    updateEmptyState();
    renderSessionList();
    scrollToBottom();
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
    bindEvents();
    updateEmptyState();
    await loadSessions();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

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
    getActiveSessionId: function () { return activeSessionId; },
    getSessions: function () { return sessions; }
  };
})();
