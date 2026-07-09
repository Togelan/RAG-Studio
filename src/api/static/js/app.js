/**
 * RAG-Studio — Client-Side Application JavaScript
 * Vanilla JS, no frameworks.
 * Handles: tab navigation, language switching, mobile menu,
 *          status indicator polling, URL hash routing.
 */

(function () {
  'use strict';

  // ============================================================
  // State
  // ============================================================

  /** @type {string} Current active tab ID */
  let currentTab = 'welcome';

  /** @type {string} Current locale ('en' | 'ru') */
  let currentLocale = 'en';

  /** @type {Object<string, string>} Translation map for current locale */
  let translations = {};

  /** Polling interval ID for status indicator */
  let statusPollInterval = null;

  // ============================================================
  // DOM References
  // ============================================================

  /** @returns {NodeListOf<Element>} All desktop nav tab buttons */
  function getNavTabs() {
    return document.querySelectorAll('.nav-tab');
  }

  /** @returns {NodeListOf<Element>} All mobile nav items */
  function getMobileNavItems() {
    return document.querySelectorAll('.mobile-nav-item');
  }

  /** @returns {NodeListOf<Element>} All mobile bottom tab buttons */
  function getMobileTabs() {
    return document.querySelectorAll('.mobile-tab');
  }

  /** @returns {NodeListOf<Element>} All language buttons */
  function getLangBtns() {
    return document.querySelectorAll('.lang-btn');
  }

  /** @returns {Element|null} The mobile nav overlay */
  function getMobileNavOverlay() {
    return document.getElementById('mobileNavOverlay');
  }

  /** @returns {Element|null} The status dot */
  function getStatusDot() {
    return document.querySelector('.status-dot');
  }

  /** @returns {Element|null} The status text */
  function getStatusText() {
    return document.querySelector('.status-text');
  }

  // ============================================================
  // Tab Navigation
  // ============================================================

  /**
   * Switch to a different tab without full page reload.
   * Updates URL hash, shows target content, updates active states.
   *
   * @param {string} tabId - The tab identifier ('welcome', 'settings', 'chat')
   */
  function switchTab(tabId) {
    if (!tabId) return;

    currentTab = tabId;

    // Hide all tab content divs
    document.querySelectorAll('.tab-content').forEach(function (el) {
      el.classList.remove('active');
      el.style.display = 'none';
    });

    // Show the target tab content
    var targetContent = document.getElementById('tab-' + tabId);
    if (targetContent) {
      targetContent.classList.add('active');
      targetContent.style.display = 'block';
    }

    // Update desktop nav tabs
    getNavTabs().forEach(function (tab) {
      var dataTab = tab.getAttribute('data-tab');
      if (dataTab === tabId) {
        tab.classList.add('active');
      } else {
        tab.classList.remove('active');
      }
    });

    // Update mobile bottom tabs
    getMobileTabs().forEach(function (tab) {
      var dataTab = tab.getAttribute('data-tab');
      if (dataTab === tabId) {
        tab.classList.add('active');
      } else {
        tab.classList.remove('active');
      }
    });

    // Update mobile nav overlay items
    getMobileNavItems().forEach(function (item) {
      var dataTab = item.getAttribute('data-tab');
      if (dataTab === tabId) {
        item.classList.add('active');
      } else {
        item.classList.remove('active');
      }
    });

    // Update URL hash
    if (window.location.hash !== '#' + tabId) {
      history.pushState(null, '', '#' + tabId);
    }

    // Close mobile overlay if open
    var overlay = getMobileNavOverlay();
    if (overlay) {
      overlay.classList.remove('active');
    }
  }

  /**
   * Navigate to a tab by loading the corresponding page
   * via a full navigation (used when the tab content is
   * loaded via separate pages).
   *
   * @param {string} tabId
   */
  function navigateToTab(tabId) {
    var pathMap = {
      'welcome': '/',
      'settings': '/settings',
      'chat': '/chat'
    };
    var path = pathMap[tabId] || '/';
    window.location.href = path;
  }

  // ============================================================
  // Language Switching
  // ============================================================

  /**
   * Switch the application locale.
   * POSTs to the backend, then updates all [data-i18n] elements.
   * Saves preference to localStorage.
   *
   * @param {string} locale - 'en' or 'ru'
   */
  function switchLanguage(locale) {
    if (locale === currentLocale) return;

    fetch('/api/ui/locale', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ locale: locale })
    })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error('Locale switch failed: ' + resp.status);
        }
        return resp.json();
      })
      .then(function (data) {
        // data.translations contains the translation map
        currentLocale = locale;
        translations = data.translations || {};

        // Update all [data-i18n] elements (textContent)
        document.querySelectorAll('[data-i18n]').forEach(function (el) {
          var key = el.getAttribute('data-i18n');
          if (key && translations[key]) {
            el.textContent = translations[key];
          }
        });

        // Update all [data-i18n-placeholder] elements (placeholder attribute)
        document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
          var key = el.getAttribute('data-i18n-placeholder');
          if (key && translations[key]) {
            el.placeholder = translations[key];
          }
        });

        // Update all [data-i18n-aria] elements (aria-label attribute)
        document.querySelectorAll('[data-i18n-aria]').forEach(function (el) {
          var key = el.getAttribute('data-i18n-aria');
          if (key && translations[key]) {
            el.setAttribute('aria-label', translations[key]);
          }
        });

        // Update all [data-i18n-title] elements (title attribute)
        document.querySelectorAll('[data-i18n-title]').forEach(function (el) {
          var key = el.getAttribute('data-i18n-title');
          if (key && translations[key]) {
            el.title = translations[key];
          }
        });

        // Update document lang attribute
        document.documentElement.lang = locale;
        document.documentElement.setAttribute('data-locale', locale);

        // Update language buttons active state
        getLangBtns().forEach(function (btn) {
          var btnLang = btn.getAttribute('data-lang');
          if (btnLang === locale) {
            btn.classList.add('active');
          } else {
            btn.classList.remove('active');
          }
        });

        // Save to localStorage
        try {
          localStorage.setItem('rag-studio-locale', locale);
        } catch (e) {
          // localStorage may be unavailable
        }

        // Update system prompt if not manually edited by user
        var promptTextarea = document.getElementById('settings-system-prompt');
        if (promptTextarea && !systemPromptEdited && !promptTextarea.getAttribute('data-edited')) {
          var defaultPrompt = DEFAULT_SYSTEM_PROMPTS[locale] || DEFAULT_SYSTEM_PROMPTS['en'];
          promptTextarea.value = defaultPrompt;
        }
      })
      .catch(function (err) {
        console.error('Language switch error:', err);
      });
  }

  // ============================================================
  // Mobile Menu (Hamburger)
  // ============================================================

  /**
   * Toggle the mobile navigation overlay.
   */
  function toggleMobileMenu() {
    var overlay = getMobileNavOverlay();
    if (overlay) {
      overlay.classList.toggle('active');
    }
  }

  // ============================================================
  // Status Indicator Polling
  // ============================================================

  /**
   * Poll the health status endpoint and update the status indicator.
   */
  function updateStatusIndicator() {
    fetch('/api/health/status')
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error('Status check failed');
        }
        return resp.json();
      })
      .then(function (data) {
        var dot = getStatusDot();
        var text = getStatusText();

        if (!dot || !text) return;

        // Remove all status classes
        dot.classList.remove('status-green', 'status-yellow', 'status-red');

        var status = data.status || 'degraded';
        var apiKeySet = data.api_key_configured || false;

        if (status === 'ready' && apiKeySet) {
          dot.classList.add('status-green');
          if (translations['status_ready']) {
            text.textContent = translations['status_ready'];
          } else {
            text.textContent = 'Ready';
          }
        } else if (status === 'ready' && !apiKeySet) {
          dot.classList.add('status-yellow');
          if (translations['status_no_api_key']) {
            text.textContent = translations['status_no_api_key'];
          } else {
            text.textContent = 'No API key';
          }
        } else {
          dot.classList.add('status-red');
          if (translations['status_disconnected']) {
            text.textContent = translations['status_disconnected'];
          } else {
            text.textContent = 'Disconnected';
          }
        }
      })
      .catch(function () {
        var dot = getStatusDot();
        var text = getStatusText();

        if (!dot || !text) return;

        dot.classList.remove('status-green', 'status-yellow', 'status-red');
        dot.classList.add('status-red');
        if (translations['status_disconnected']) {
          text.textContent = translations['status_disconnected'];
        } else {
          text.textContent = 'Disconnected';
        }
      });
  }

  /**
   * Start periodic status polling.
   */
  function startStatusPolling() {
    updateStatusIndicator();
    statusPollInterval = setInterval(updateStatusIndicator, 30000);
  }

  /**
   * Stop periodic status polling.
   */
  function stopStatusPolling() {
    if (statusPollInterval) {
      clearInterval(statusPollInterval);
      statusPollInterval = null;
    }
  }

  // ============================================================
  // Initialization
  // ============================================================

  /**
   * Initialize the application on DOMContentLoaded.
   * Reads URL hash, localStorage locale, binds event handlers.
   */
  function initializeApp() {
    // 1. Determine active tab from URL hash
    var hash = window.location.hash.replace('#', '');
    if (hash && ['welcome', 'settings', 'chat'].indexOf(hash) !== -1) {
      currentTab = hash;
    }

    // 2. Read locale from localStorage
    try {
      var savedLocale = localStorage.getItem('rag-studio-locale');
      if (savedLocale && (savedLocale === 'en' || savedLocale === 'ru')) {
        currentLocale = savedLocale;
      } else {
        // Fall back to document data-locale attribute
        currentLocale = document.documentElement.getAttribute('data-locale') || 'en';
      }
    } catch (e) {
      currentLocale = document.documentElement.getAttribute('data-locale') || 'en';
    }

    // 3. If on a page with tab-content divs, set the active tab
    var activeContent = document.getElementById('tab-' + currentTab);
    if (activeContent) {
      switchTab(currentTab);
    }

    // 4. Bind desktop nav tab clicks
    getNavTabs().forEach(function (tab) {
      tab.addEventListener('click', function () {
        var tabId = this.getAttribute('data-tab');
        if (tabId) {
          // Check if we're on a multi-tab page or single page
          var targetContent = document.getElementById('tab-' + tabId);
          if (targetContent) {
            switchTab(tabId);
          } else {
            navigateToTab(tabId);
          }
        }
      });
    });

    // 5. Bind mobile bottom tab clicks
    getMobileTabs().forEach(function (tab) {
      tab.addEventListener('click', function () {
        var tabId = this.getAttribute('data-tab');
        if (tabId) {
          var targetContent = document.getElementById('tab-' + tabId);
          if (targetContent) {
            switchTab(tabId);
          } else {
            navigateToTab(tabId);
          }
        }
      });
    });

    // 6. Bind mobile nav overlay item clicks
    getMobileNavItems().forEach(function (item) {
      item.addEventListener('click', function () {
        var tabId = this.getAttribute('data-tab');
        if (tabId) {
          var targetContent = document.getElementById('tab-' + tabId);
          if (targetContent) {
            switchTab(tabId);
          } else {
            navigateToTab(tabId);
          }
        }
      });
    });

    // 7. Bind language switcher clicks
    getLangBtns().forEach(function (btn) {
      btn.addEventListener('click', function () {
        var lang = this.getAttribute('data-lang');
        if (lang) {
          switchLanguage(lang);
        }
      });
    });

    // 8. Start status polling
    startStatusPolling();

    // 9. Handle browser back/forward
    window.addEventListener('popstate', function () {
      var newHash = window.location.hash.replace('#', '');
      if (newHash && ['welcome', 'settings', 'chat'].indexOf(newHash) !== -1) {
        var target = document.getElementById('tab-' + newHash);
        if (target) {
          switchTab(newHash);
        }
      }
    });

    // 10. If saved locale differs from current, apply it
    var docLocale = document.documentElement.getAttribute('data-locale') || 'en';
    if (currentLocale !== docLocale) {
      switchLanguage(currentLocale);
    }

    // 11. Initialize welcome page features (counters, CTA button)
    initWelcomeCounters();
    initGetStartedButton();

    // 12. Check if we should auto-focus the API key input (from welcome CTA)
    checkApiKeyFocus();

    // 13. Initialize settings page features
    initSettingsPage();
    initSaveSettingsButton();
    initDocumentUpload();
    initLangSmithModal();
    initSystemPromptReset();
  }

  // ============================================================
  // Welcome Page — Animated Counters
  // ============================================================

  /**
   * Animate counter cards using IntersectionObserver + requestAnimationFrame.
   * Counts from 0 to the target value over 2000ms with easeOutQuad easing.
   */
  function initWelcomeCounters() {
    var counters = document.querySelectorAll('.counter-card[data-counter]');
    if (!counters.length) return;

    /**
     * Ease-out quadratic easing function.
     * @param {number} t - Progress from 0 to 1
     * @returns {number} Eased progress
     */
    function easeOutQuad(t) {
      return t * (2 - t);
    }

    /**
     * Animate a single counter element from 0 to its target value.
     * @param {Element} card - The .counter-card element
     */
    function animateCounter(card) {
      var target = parseInt(card.getAttribute('data-counter'), 10);
      if (isNaN(target) || target <= 0) return;

      var numberEl = card.querySelector('.counter-number');
      if (!numberEl) return;

      var duration = 2000; // ms
      var startTime = null;

      /**
       * requestAnimationFrame step function.
       * @param {DOMHighResTimeStamp} timestamp
       */
      function step(timestamp) {
        if (!startTime) startTime = timestamp;
        var elapsed = timestamp - startTime;
        var progress = Math.min(elapsed / duration, 1);
        var easedProgress = easeOutQuad(progress);
        var currentValue = Math.round(easedProgress * target);
        numberEl.textContent = String(currentValue);
        if (progress < 1) {
          requestAnimationFrame(step);
        }
      }

      requestAnimationFrame(step);
    }

    // Use IntersectionObserver to trigger animation when counters become visible
    if ('IntersectionObserver' in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            animateCounter(entry.target);
            observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.3 });

      counters.forEach(function (card) {
        observer.observe(card);
      });
    } else {
      // Fallback: animate immediately
      counters.forEach(function (card) {
        animateCounter(card);
      });
    }
  }

  // ============================================================
  // Welcome Page — Get Started CTA Button
  // ============================================================

  /**
   * Bind click handler to the "Get Started" button.
   * Sets sessionStorage flag and navigates to Settings page.
   */
  function initGetStartedButton() {
    var btn = document.getElementById('btn-get-started');
    if (!btn) return;

    btn.addEventListener('click', function () {
      try {
        sessionStorage.setItem('focus-api-key', 'true');
      } catch (e) {
        // sessionStorage may be unavailable
      }
      navigateToTab('settings');
    });
  }

  /**
   * Check if we should auto-focus the API key input on the Settings page.
   * Reads the sessionStorage flag set by the Get Started CTA button.
   */
  function checkApiKeyFocus() {
    var shouldFocus = false;
    try {
      shouldFocus = sessionStorage.getItem('focus-api-key') === 'true';
    } catch (e) {
      return;
    }

    if (!shouldFocus) return;

    // Clear the flag immediately to prevent re-focus on subsequent loads
    try {
      sessionStorage.removeItem('focus-api-key');
    } catch (e) {
      // ignore
    }

    // Wait a short delay to ensure DOM is ready
    setTimeout(function () {
      var apiKeyInput = document.getElementById('settings-api-key');
      if (apiKeyInput) {
        apiKeyInput.focus();
      }
    }, 100);
  }

  // ============================================================
  // Settings Page — Provider → Model Mapping
  // ============================================================

  /**
   * Provider-to-model mapping for settings page.
   * Ollama uses a text input instead of a dropdown.
   * @type {Object<string, string[]>}
   */
  var PROVIDER_MODELS = {
    openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-3.5-turbo'],
    deepseek: ['deepseek-chat', 'deepseek-coder'],
    anthropic: ['claude-sonnet-5', 'claude-opus-4-8', 'claude-haiku-4-5'],
    ollama: []  // text input — no preset options
  };

  /**
   * Default system prompts keyed by locale.
   * @type {Object<string, string>}
   */
  var DEFAULT_SYSTEM_PROMPTS = {
    en: 'You are RAG-Studio AI assistant. Answer strictly based on the provided context. If you don\'t know, say so.',
    ru: 'Ты — AI-ассистент RAG-Studio. Отвечай строго по загруженным документам. Если не знаешь, скажи об этом.'
  };

  /** @type {boolean} Whether the user has manually edited the system prompt */
  var systemPromptEdited = false;

  /** @type {number|null} Original chunk size loaded from GET /api/settings */
  var originalChunkSize = null;

  /** @type {number|null} Original chunk overlap loaded from GET /api/settings */
  var originalChunkOverlap = null;

  /**
   * Monotonically increasing request counter for model fetches.
   * Used to discard stale responses when the user rapidly switches providers.
   * @type {number}
   */
  var _modelFetchCounter = 0;

  /**
   * Update the slider track fill to show accent color up to the thumb position.
   * Creates a smooth visual progress effect using a CSS linear-gradient.
   * @param {Element} slider - The range input element
   */
  function _updateSliderTrackFill(slider) {
    if (!slider) return;
    var min = parseFloat(slider.min) || 0;
    var max = parseFloat(slider.max) || 2;
    var val = parseFloat(slider.value) || 0;
    var pct = max > min ? ((val - min) / (max - min)) * 100 : 0;
    slider.style.background = 'linear-gradient(to right, var(--color-accent) ' + pct + '%, var(--color-border) ' + pct + '%)';
  }

  /**
   * Update the temperature slider range based on the selected provider.
   * Anthropic: 0.0–1.0 (max 1.0). Others: 0.0–2.0 (max 2.0).
   * Clamps the current value if it exceeds the new max.
   * @param {string} provider - The selected provider name
   */
  function _updateTemperatureRange(provider) {
    var tempSlider = document.getElementById('settings-temperature');
    var tempValue = document.getElementById('temp-value');
    if (!tempSlider) return;

    var newMax = provider === 'anthropic' ? '1.0' : '2.0';
    tempSlider.max = newMax;

    // Clamp current value if it exceeds the new max, or update display
    var currentVal = parseFloat(tempSlider.value);
    var maxVal = parseFloat(newMax);
    if (currentVal > maxVal) {
      tempSlider.value = newMax;
    }
    // Always refresh display to match the (possibly clamped) value
    if (tempValue) {
      tempValue.textContent = parseFloat(tempSlider.value).toFixed(2);
    }
    // Update track fill
    _updateSliderTrackFill(tempSlider);
  }

  /**
   * Apply Ollama-specific UI changes synchronously:
   * - Replace model <select> with a text <input>
   * - Disable the API key input (grayed out, not hidden)
   * @param {Element} modelContainer - The model select/input element
   * @param {Element|null} apiKeyCard - The API key input element
   * @returns {Element} The new text input element (or unchanged element if already an input)
   */
  function _applyOllamaUI(modelContainer, apiKeyCard) {
    if (modelContainer.tagName === 'SELECT') {
      var input = document.createElement('input');
      input.type = 'text';
      input.id = 'settings-model';
      input.className = 'input-field';
      input.setAttribute('data-testid', 'model-select');
      input.placeholder = 'e.g. llama3, mistral';
      input.value = '';
      modelContainer.replaceWith(input);
      modelContainer = input;
    }
    // Disable API key input for Ollama (keep visible but grayed out)
    if (apiKeyCard) {
      apiKeyCard.disabled = true;
      apiKeyCard.style.pointerEvents = 'none';
      apiKeyCard.style.opacity = '0.6';
      apiKeyCard.style.backgroundColor = '#e0e0e0';
      apiKeyCard.placeholder = translations['settings_api_key_ollama_placeholder'] || 'Not required for local models';
    }
    return modelContainer;
  }

  /**
   * Apply cloud-provider UI changes synchronously:
   * - Re-enable the API key input with normal styling
   * - Replace model <input> with a <select> (if it was an input from Ollama)
   * @param {Element} modelContainer - The model select/input element
   * @param {Element|null} apiKeyCard - The API key input element
   * @returns {Element} The select element (new or existing)
   */
  function _applyCloudUI(modelContainer, apiKeyCard) {
    // Re-query the API key card in case the DOM was modified
    if (!apiKeyCard || !document.body.contains(apiKeyCard)) {
      apiKeyCard = document.getElementById('settings-api-key');
    }
    // Re-enable API key input for cloud providers.
    // Preserve the bullet-dot placeholder if a key was already saved;
    // otherwise show the default 'sk-...' hint.
    if (apiKeyCard) {
      apiKeyCard.disabled = false;
      apiKeyCard.style.pointerEvents = '';
      apiKeyCard.style.opacity = '';
      apiKeyCard.style.backgroundColor = '';
      if (apiKeyCard.placeholder !== '••••••••') {
        apiKeyCard.placeholder = 'sk-...';
      }
    }
    // If coming from Ollama text input, replace with a select
    if (modelContainer.tagName === 'INPUT') {
      var select = document.createElement('select');
      select.id = 'settings-model';
      select.className = 'input-field';
      select.setAttribute('data-testid', 'model-select');
      modelContainer.replaceWith(select);
      modelContainer = select;
    }
    return modelContainer;
  }

  /**
   * Update the model selector based on the currently selected provider.
   * For Ollama: replace <select> with <input type="text"> instantly,
   * hide API key instantly, THEN fetch models asynchronously.
   * For cloud providers: show API key instantly, show loading state,
   * THEN fetch and populate models asynchronously.
   */
  function updateModelSelector() {
    var provider = document.getElementById('settings-provider');
    var modelContainer = document.getElementById('settings-model');
    var apiKeyCard = document.getElementById('settings-api-key');
    if (!provider || !modelContainer) return;

    var selectedProvider = provider.value;

    if (selectedProvider === 'ollama') {
      // Apply Ollama UI changes synchronously — no latency
      modelContainer = _applyOllamaUI(modelContainer, apiKeyCard);
      // Update temperature range
      _updateTemperatureRange(selectedProvider);
      // Still fetch models in background (for potential local model list),
      // but the UI is already updated
      var requestId = ++_modelFetchCounter;
      fetch('/api/settings/models/ollama')
        .then(function (resp) { return resp.ok ? resp.json() : Promise.reject(); })
        .then(function () { /* models fetched — no UI update needed for Ollama */ })
        .catch(function () { /* fallback not needed — UI already correct */ });
      return;
    }

    // Cloud provider: show API key card, update temperature range, and loading state immediately
    modelContainer = _applyCloudUI(modelContainer, apiKeyCard);
    _updateTemperatureRange(selectedProvider);
    _setModelLoading(modelContainer);

    var requestId = ++_modelFetchCounter;

    // Fetch models from backend
    fetch('/api/settings/models/' + encodeURIComponent(selectedProvider))
      .then(function (resp) {
        if (!resp.ok) throw new Error('Failed to fetch models');
        return resp.json();
      })
      .then(function (data) {
        // Discard stale response if a newer request was issued
        if (requestId !== _modelFetchCounter) return;
        var models = data.models || [];
        _populateModelSelector(modelContainer, models, selectedProvider);
      })
      .catch(function () {
        // Discard stale response if a newer request was issued
        if (requestId !== _modelFetchCounter) return;
        // Fallback to hardcoded list
        var fallback = PROVIDER_MODELS[selectedProvider] || [];
        _populateModelSelector(modelContainer, fallback, selectedProvider);
      });
  }

  /**
   * Set the model selector to a loading state.
   * @param {Element} container - The model select/input element
   */
  function _setModelLoading(container) {
    if (container.tagName === 'SELECT') {
      container.innerHTML = '';
      var opt = document.createElement('option');
      opt.textContent = translations['settings_loading_models'] || 'Loading models...';
      opt.disabled = true;
      container.appendChild(opt);
    }
    // For INPUT elements (Ollama text input), do nothing — the loading
    // state is not meaningful here; _populateModelSelector will replace
    // the input with a select once the fetch completes.
  }

  /**
   * Populate the model selector with the given models list.
   * Called only for cloud providers (Ollama UI is applied synchronously
   * in _applyOllamaUI). The container is always a <select> at this point.
   * @param {Element} container - The model <select> element
   * @param {string[]} models - List of model names
   * @param {string} provider - Selected provider name (unused, for clarity)
   */
  function _populateModelSelector(container, models, provider) {
    container.innerHTML = '';
    models.forEach(function (m) {
      var opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m;
      container.appendChild(opt);
    });
  }

  /**
   * Load saved settings from GET /api/settings and populate the form.
   * Sets provider dropdown, model selector, API key placeholder,
   * temperature slider, max tokens, and system prompt.
   */
  function loadSettings() {
    var loadedProvider = null;

    fetch('/api/settings')
      .then(function (resp) {
        if (!resp.ok) throw new Error('Failed to load settings');
        return resp.json();
      })
      .then(function (data) {
        loadedProvider = data.provider || 'openai';

        // Set provider dropdown
        var providerEl = document.getElementById('settings-provider');
        if (providerEl && loadedProvider) {
          providerEl.value = loadedProvider;
        }

        // Set temperature slider (value first, then clamp range)
        var tempSlider = document.getElementById('settings-temperature');
        var tempValue = document.getElementById('temp-value');
        if (tempSlider && data.temperature != null) {
          tempSlider.value = String(data.temperature);
          if (tempValue) {
            tempValue.textContent = Number(data.temperature).toFixed(2);
          }
        }

        // Apply temperature range AFTER setting the value,
        // so clamping and display are correct for the provider.
        _updateTemperatureRange(loadedProvider);

        // Update track fill to match the loaded value
        var tempSlider = document.getElementById('settings-temperature');
        _updateSliderTrackFill(tempSlider);

        // Set max tokens
        var maxTokens = document.getElementById('settings-max-tokens');
        if (maxTokens && data.max_tokens != null) {
          maxTokens.value = String(data.max_tokens);
        }

        // Set top-k
        var topK = document.getElementById('settings-top-k');
        if (topK && data.top_k != null) {
          topK.value = String(data.top_k);
        }
        // Set chunk size
        var chunkSize = document.getElementById('settings-chunk-size');
        if (chunkSize && data.chunk_size != null) {
          chunkSize.value = String(data.chunk_size);
        }
        // Set chunk overlap
        var chunkOverlap = document.getElementById('settings-chunk-overlap');
        if (chunkOverlap && data.chunk_overlap != null) {
          chunkOverlap.value = String(data.chunk_overlap);
        }

        // Set system prompt
        var systemPrompt = document.getElementById('settings-system-prompt');
        if (systemPrompt && data.system_prompt) {
          systemPrompt.value = data.system_prompt;
        }

        // Now that the provider dropdown is set to the saved value,
        // fetch and populate the correct model list for that provider.
        // MUST call this BEFORE setting the API key placeholder because
        // updateModelSelector() → _applyCloudUI() resets the placeholder
        // to 'sk-...', which would overwrite the bullet dots.
        updateModelSelector();

        // Set API key placeholder to bullet dots if a key has been saved.
        // The backend sends "********" as a sentinel value; we display
        // bullet dots in the UI to avoid confusion with a real key.
        var apiKeyInput = document.getElementById('settings-api-key');
        if (apiKeyInput && data.api_key) {
          apiKeyInput.placeholder = '••••••••';
          apiKeyInput.value = '';
        }

        // Capture original chunk settings for change detection (FR-010)
        captureOriginalChunkSettings();

        // Reveal the settings form now that everything is initialized.
        // This prevents the flash of hardcoded HTML defaults (wrong provider/models).
        var layout = document.getElementById('settings-layout');
        if (layout) {
          layout.style.visibility = 'visible';
        }
      })
      .catch(function (err) {
        console.error('Failed to load settings:', err);
      });
  }

  /**
   * Initialize the settings page — provider change handler,
   * temperature slider live update, refresh models button, and model sync on load.
   */
  function initSettingsPage() {
    var providerEl = document.getElementById('settings-provider');
    var tempSlider = document.getElementById('settings-temperature');
    var tempValue = document.getElementById('temp-value');
    var refreshBtn = document.getElementById('btn-refresh-models');

    if (!providerEl && !tempSlider) return; // Not on settings page

    // Load saved settings from backend.
    // updateModelSelector() is called from within loadSettings() after
    // the provider dropdown has been set to the saved value, avoiding
    // a race condition where models for the wrong provider are loaded.
    loadSettings();

    // Provider change → update model selector
    if (providerEl) {
      providerEl.addEventListener('change', updateModelSelector);
    }

    // Refresh models button
    if (refreshBtn) {
      refreshBtn.addEventListener('click', function () {
        updateModelSelector();
      });
    }

    // Temperature slider → live update display value
    if (tempSlider && tempValue) {
      tempSlider.addEventListener('input', function () {
        var val = parseFloat(tempSlider.value);
        tempValue.textContent = val.toFixed(2);
        _updateSliderTrackFill(tempSlider);
      });
    }
  }

  // ============================================================
  // Settings Page — Save Settings Button
  // ============================================================

  /**
   * Bind click handler to the Save Settings button.
   * POSTs settings to /api/settings, then validates API key if provided.
   * Handles re-ingestion modal for chunk setting changes (FR-010).
   */
  function initSaveSettingsButton() {
    var btn = document.getElementById('btn-save-settings');
    if (!btn) return;

    btn.addEventListener('click', async function () {
      var statusEl = document.getElementById('settings-save-status');
      var provider = document.getElementById('settings-provider');
      var modelEl = document.getElementById('settings-model');
      var tempSlider = document.getElementById('settings-temperature');
      var maxTokens = document.getElementById('settings-max-tokens');
      var topK = document.getElementById('settings-top-k');
      var chunkSize = document.getElementById('settings-chunk-size');
      var chunkOverlap = document.getElementById('settings-chunk-overlap');
      var systemPrompt = document.getElementById('settings-system-prompt');
      var apiKeyInput = document.getElementById('settings-api-key');

      if (!provider || !modelEl) return;

      // v1.0: only DeepSeek is supported. Silently override any other provider.
      if (provider.value !== 'deepseek') {
        provider.value = 'deepseek';
      }

      var settings = {
        provider: provider.value,
        model: modelEl.value || modelEl.placeholder,
        temperature: tempSlider ? parseFloat(tempSlider.value) : 1.0,
        max_tokens: maxTokens ? parseInt(maxTokens.value, 10) : 2048,
        system_prompt: systemPrompt ? systemPrompt.value : '',
        top_k: topK ? parseInt(topK.value, 10) : 5,
        chunk_size: chunkSize ? parseInt(chunkSize.value, 10) : 512,
        chunk_overlap: chunkOverlap ? parseInt(chunkOverlap.value, 10) : 64
      };

      // FR-010: Check if re-ingestion is needed before saving
      var shouldContinue = await handleSettingsSave();
      if (!shouldContinue) {
        return; // User dismissed or re-ingestion is in progress
      }

      // Show saving state
      if (statusEl) {
        statusEl.textContent = translations['settings_validating'] || 'Validating...';
        statusEl.className = 'settings-save-status status-info';
      }

      // Step 1: Save settings
      fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      })
        .then(function (resp) {
          if (!resp.ok) {
            return resp.json().then(function (data) {
              throw new Error(data.detail || 'Save failed');
            });
          }
          return resp.json();
        })
        .then(function () {
          // Step 2: Validate API key if provided
          if (apiKeyInput && apiKeyInput.value.trim()) {
            return fetch('/api/settings/validate-key', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                provider: provider.value,
                api_key: apiKeyInput.value.trim()
              })
            }).then(function (resp) {
              return resp.json();
            }).then(function (data) {
              if (!data.valid) {
                throw new Error(data.error || (translations['settings_invalid_key'] || 'Invalid API key'));
              }
            });
          }
        })
        .then(function () {
          if (statusEl) {
            statusEl.textContent = translations['settings_saved'] || 'Settings saved!';
            statusEl.className = 'settings-save-status status-success';
            setTimeout(function () {
              statusEl.textContent = '';
              statusEl.className = 'settings-save-status';
            }, 3000);
          }
          // Clear API key input and show bullet dots after successful save.
          // This prevents the plaintext key from remaining visible in the UI.
          if (apiKeyInput && apiKeyInput.value.trim()) {
            apiKeyInput.value = '';
            apiKeyInput.placeholder = '••••••••';
          }
          // Refresh original chunk settings after save
          captureOriginalChunkSettings();
        })
        .catch(function (err) {
          if (statusEl) {
            statusEl.textContent = err.message || (translations['settings_save_error'] || 'Failed to save settings.');
            statusEl.className = 'settings-save-status status-error';
          }
        });
    });
  }

  // ============================================================
  // Settings Page — Re-Ingestion Flow (FR-010)
  // ============================================================

  /**
   * Store original chunk settings from the form for change detection.
   * Called after settings are loaded from GET /api/settings.
   */
  function captureOriginalChunkSettings() {
    var chunkSizeEl = document.getElementById('settings-chunk-size');
    var chunkOverlapEl = document.getElementById('settings-chunk-overlap');
    originalChunkSize = chunkSizeEl ? parseInt(chunkSizeEl.value, 10) : 512;
    originalChunkOverlap = chunkOverlapEl ? parseInt(chunkOverlapEl.value, 10) : 64;
  }

  /**
   * Check if chunk-related settings changed and handle re-ingestion flow.
   * Called before saving settings.
   * @returns {Promise<boolean>} true if save should proceed
   */
  async function handleSettingsSave() {
    var newChunkSize = parseInt(document.getElementById('settings-chunk-size')?.value || '512');
    var newChunkOverlap = parseInt(document.getElementById('settings-chunk-overlap')?.value || '64');

    var chunksChanged = (originalChunkSize !== null && originalChunkSize !== newChunkSize) ||
                        (originalChunkOverlap !== null && originalChunkOverlap !== newChunkOverlap);

    if (!chunksChanged) {
      return true; // No chunk changes, save normally (AC-010.5)
    }

    // Check if documents exist (AC-010.1: no docs → silent save)
    try {
      var resp = await fetch('/api/ingest/documents');
      var data = await resp.json();
      if (!data.documents || data.documents.length === 0) {
        return true; // No documents, save silently (AC-010.1)
      }
    } catch (e) {
      return true; // If we can't check, proceed
    }

    // Show the re-ingestion modal and wait for user choice (AC-010.2)
    return new Promise(function (resolve) {
      var modal = document.getElementById('reingestModal');
      var skipBtn = document.getElementById('reingest-modal-skip');
      var confirmBtn = document.getElementById('reingest-modal-confirm');
      var progressContainer = document.getElementById('reingest-progress-container');
      var progressBar = document.getElementById('reingest-progress-bar');
      var progressText = document.getElementById('reingest-progress-text');

      // Re-enable buttons (may be disabled from a previous re-ingestion)
      skipBtn.disabled = false;
      confirmBtn.disabled = false;
      // Reset progress container to hidden state
      if (progressContainer) {
        progressContainer.style.display = 'none';
      }

      function hideModal() {
        modal.style.display = 'none';
        progressContainer.style.display = 'none';
      }

      function cleanup() {
        skipBtn.removeEventListener('click', onSkip);
        confirmBtn.removeEventListener('click', onReingest);
      }

      function onSkip() {
        cleanup();
        hideModal();
        resolve(true); // Save settings without re-ingestion (AC-010.3)
      }

      async function onReingest() {
        cleanup();
        // Disable buttons, show progress (AC-010.4)
        skipBtn.disabled = true;
        confirmBtn.disabled = true;
        progressContainer.style.display = 'block';

        try {
          // Get document list before clearing
          var docsResp = await fetch('/api/ingest/documents');
          var docsData = await docsResp.json();
          var documents = docsData.documents || [];

          if (documents.length === 0) {
            hideModal();
            resolve(true);
            return;
          }

          // Clear all documents
          await fetch('/api/ingest/clear', { method: 'DELETE' });

          // Re-ingest each document
          var completed = 0;
          var errors = 0;
          var total = documents.length;

          for (var i = 0; i < documents.length; i++) {
            var doc = documents[i];
            progressText.textContent = (translations['reingest_progress'] || 'Re-ingesting documents...') +
              ' (' + (completed + 1) + '/' + total + ')';
            progressBar.style.width = Math.round((completed / total) * 100) + '%';

            try {
              var reingestResp = await fetch('/api/ingest/reingest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ doc_id: doc.doc_id, filename: doc.filename }),
              });

              if (reingestResp.ok) {
                var result = await reingestResp.json();
                if (result.status === 'skipped') {
                  // Source file no longer exists — skip silently (already cleared from Qdrant)
                  completed++;
                } else {
                  // Poll for completion
                  await pollReingestionProgress(result.file_id);
                  completed++;
                }
              } else {
                // AC-010.6: failed document — skip with toast
                errors++;
                completed++;
                var errData = await reingestResp.json().catch(function() { return {}; });
                showToast(
                  (translations['reingest_error'] || 'Re-ingestion failed.') +
                  ' ' + doc.filename + ': ' + (errData.detail || 'Unknown error'),
                  'error'
                );
              }
            } catch (e) {
              // AC-010.6: failed document — skip, continue
              errors++;
              completed++;
              showToast(
                (translations['reingest_error'] || 'Re-ingestion failed.') +
                ' ' + doc.filename,
                'error'
              );
            }
          }

          progressBar.style.width = '100%';
          if (errors > 0) {
            progressText.textContent = translations['reingest_complete_errors'] || 'Re-ingestion completed with errors.';
          } else {
            progressText.textContent = translations['reingest_complete'] || 'Re-ingestion complete.';
          }

          // Refresh document table
          loadDocumentList();

          // Close modal after short delay
          setTimeout(function () {
            hideModal();
            resolve(true);
          }, 2000);

        } catch (e) {
          hideModal();
          resolve(true);
        }
      }

      skipBtn.addEventListener('click', onSkip);
      confirmBtn.addEventListener('click', onReingest);
      modal.style.display = 'flex';

      // Focus the Skip button by default (safe choice)
      skipBtn.focus();
    });
  }

  /**
   * Poll ingestion progress for re-ingestion until done or error.
   * @param {string} fileId
   * @returns {Promise<void>}
   */
  function pollReingestionProgress(fileId) {
    return new Promise(function (resolve, reject) {
      var maxPolls = 120; // 2 minutes max
      var polls = 0;

      var interval = setInterval(function () {
        fetch('/api/ingest/progress/' + fileId)
          .then(function (resp) {
            if (!resp.ok) throw new Error('Progress check failed');
            return resp.json();
          })
          .then(function (data) {
            polls++;
            if (data.status === 'done') {
              clearInterval(interval);
              resolve();
            } else if (data.status === 'error') {
              clearInterval(interval);
              reject(new Error(data.error || data.message || 'Ingestion failed'));
            } else if (polls >= maxPolls) {
              clearInterval(interval);
              reject(new Error('Ingestion timed out'));
            }
          })
          .catch(function (err) {
            polls++;
            if (polls >= maxPolls) {
              clearInterval(interval);
              reject(err);
            }
          });
      }, 1000);
    });
  }

  // ============================================================
  // Settings Page — Document Upload (Drag & Drop + Browse)
  // ============================================================

  /**
   * Initialize document upload: file browse button, drag-and-drop,
   * progress polling, and document list loading.
   */
  function initDocumentUpload() {
    var dropzone = document.getElementById('upload-dropzone');
    if (!dropzone) return; // Not on settings page

    var fileInput = document.getElementById('file-input');
    var browseBtn = document.getElementById('btn-browse-files');

    // Browse button → trigger file input
    if (browseBtn && fileInput) {
      browseBtn.addEventListener('click', function () {
        fileInput.click();
      });

      fileInput.addEventListener('change', function () {
        if (fileInput.files && fileInput.files.length > 0) {
          uploadFiles(fileInput.files);
          fileInput.value = '';
        }
      });
    }

    // Drag-and-drop handlers
    dropzone.addEventListener('dragover', function (e) {
      e.preventDefault();
      dropzone.classList.add('drag-over');
    });

    dropzone.addEventListener('dragleave', function () {
      dropzone.classList.remove('drag-over');
    });

    dropzone.addEventListener('drop', function (e) {
      e.preventDefault();
      dropzone.classList.remove('drag-over');
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        uploadFiles(e.dataTransfer.files);
      }
    });

    // Load existing document list
    loadDocumentList();
  }

  /**
   * Upload one or more files via POST /api/ingest/upload,
   * then poll progress for each until done.
   * @param {FileList|Array<File>} files - Files to upload
   */
  function uploadFiles(files) {
    var progressContainer = document.getElementById('upload-progress');
    if (progressContainer) {
      // Clear any stale error/progress items from previous uploads
      progressContainer.innerHTML = '';
      progressContainer.style.display = 'block';
    }

    Array.prototype.forEach.call(files, function (file) {
      var formData = new FormData();
      formData.append('file', file);

      // Create progress item element
      var progressItem = document.createElement('div');
      progressItem.className = 'progress-item';
      progressItem.innerHTML =
        '<span class="progress-filename">' + file.name + '</span>' +
        '<span class="progress-status">' + (translations['settings_uploading'] || 'Uploading...') + '</span>' +
        '<div class="progress-bar-track"><div class="progress-bar-fill" style="width:20%;"></div></div>';

      if (progressContainer) {
        progressContainer.appendChild(progressItem);
      }

      var statusEl = progressItem.querySelector('.progress-status');
      var fillEl = progressItem.querySelector('.progress-bar-fill');

      fetch('/api/ingest/upload', {
        method: 'POST',
        body: formData
      })
        .then(function (resp) {
          if (resp.status === 409) {
            // Duplicate file detected (AC-001.8)
            return resp.json().then(function (data) {
              // Show duplicate modal and wait for user choice
              return showDuplicateModal(file, data, progressItem).then(function (choice) {
                if (!choice || choice.action === 'cancel') {
                  return { status: 'cancelled' };
                }
                // Re-upload with the chosen action
                var actionFormData = new FormData();
                actionFormData.append('file', file);
                return fetch('/api/ingest/upload?action=' + choice.action, {
                  method: 'POST',
                  body: actionFormData
                }).then(function (r) {
                  if (!r.ok) {
                    return r.json().then(function (errData) {
                      throw new Error(errData.detail || 'Upload failed');
                    });
                  }
                  return r.json();
                });
              });
            });
          }
          if (!resp.ok) {
            return resp.json().then(function (data) {
              throw new Error(data.detail || 'Upload failed');
            });
          }
          return resp.json();
        })
        .then(function (data) {
          if (!data || data.status === 'cancelled') {
            // User cancelled the duplicate modal
            if (progressItem.parentNode) {
              progressItem.remove();
            }
            if (progressContainer && progressContainer.children.length === 0) {
              progressContainer.style.display = 'none';
            }
            return;
          }
          if (data.status === 'unchanged') {
            // Byte-for-byte identical file (AC-001.10)
            if (statusEl) {
              statusEl.textContent = translations['duplicate_unchanged'] || 'File content is identical; skipping ingestion.';
            }
            progressItem.classList.add('progress-done');
            if (fillEl) fillEl.style.width = '100%';
            setTimeout(function () {
              if (progressItem.parentNode) progressItem.remove();
              if (progressContainer && progressContainer.children.length === 0) {
                progressContainer.style.display = 'none';
              }
            }, 3000);
            return;
          }
          var fileId = data.file_id;
          if (statusEl) {
            statusEl.textContent = translations['settings_processing'] || 'Processing...';
          }
          if (fillEl) {
            fillEl.style.width = '40%';
          }
          // Poll progress every 2 seconds
          return pollIngestionProgress(fileId, statusEl, fillEl);
        })
        .then(function () {
          if (statusEl) {
            statusEl.textContent = '✓ Done';
            progressItem.classList.add('progress-done');
          }
          if (fillEl) {
            fillEl.style.width = '100%';
          }
          // Refresh document list
          loadDocumentList();
          // Remove progress item after 3 seconds
          setTimeout(function () {
            if (progressItem.parentNode) {
              progressItem.remove();
            }
            // Hide progress container if empty
            if (progressContainer && progressContainer.children.length === 0) {
              progressContainer.style.display = 'none';
            }
          }, 3000);
        })
        .catch(function (err) {
          if (statusEl) {
            statusEl.textContent = '✗ ' + (err.message || 'Error');
          }
          progressItem.classList.add('progress-error');
          // Auto-remove error item after 5 seconds and refresh the document list
          setTimeout(function () {
            if (progressItem.parentNode) {
              progressItem.remove();
            }
            // Hide progress container if empty
            if (progressContainer && progressContainer.children.length === 0) {
              progressContainer.style.display = 'none';
            }
          }, 5000);
        });
    });
  }

  /**
   * Poll ingestion progress until done or error.
   * @param {string} fileId - The file ID from the upload response
   * @param {Element|null} statusEl - Status text element to update
   * @param {Element|null} fillEl - Progress bar fill element to animate
   * @returns {Promise<void>}
   */
  function pollIngestionProgress(fileId, statusEl, fillEl) {
    return new Promise(function (resolve, reject) {
      var attempts = 0;
      var maxAttempts = 60; // 2 minutes at 2s intervals

      function check() {
        attempts++;
        fetch('/api/ingest/progress/' + fileId)
          .then(function (resp) {
            if (!resp.ok) throw new Error('Progress check failed');
            return resp.json();
          })
          .then(function (data) {
            if (data.status === 'done') {
              resolve();
            } else if (data.status === 'error') {
              reject(new Error(data.error || data.message || 'Ingestion failed'));
            } else if (attempts >= maxAttempts) {
              reject(new Error('Ingestion timed out'));
            } else {
              // Update progress bar while processing
              if (fillEl) {
                var pct = Math.min(40 + (attempts / maxAttempts) * 50, 90);
                fillEl.style.width = pct + '%';
              }
              if (statusEl) {
                statusEl.textContent = data.message || (translations['settings_processing'] || 'Processing...');
              }
              setTimeout(check, 2000);
            }
          })
          .catch(function (err) {
            if (attempts >= maxAttempts) {
              reject(err);
            } else {
              setTimeout(check, 2000);
            }
          });
      }

      check();
    });
  }

  /**
   * Format an ISO timestamp string as local date-time (YYYY-MM-DD HH:MM).
   * @param {string|null} isoStr - ISO 8601 timestamp.
   * @returns {string} Formatted date-time or '—' if invalid.
   */
  function formatDateTime(isoStr) {
    if (!isoStr) return '—';
    var d = new Date(isoStr);
    if (isNaN(d.getTime())) return '—';
    var yyyy = d.getFullYear();
    var mm = String(d.getMonth() + 1).padStart(2, '0');
    var dd = String(d.getDate()).padStart(2, '0');
    var hh = String(d.getHours()).padStart(2, '0');
    var min = String(d.getMinutes()).padStart(2, '0');
    return yyyy + '-' + mm + '-' + dd + ' ' + hh + ':' + min;
  }

  /**
   * Load the list of ingested documents from GET /api/ingest/documents
   * and populate the document table.
   */
  function loadDocumentList() {
    var tbody = document.getElementById('doc-table-body');
    if (!tbody) return;

    fetch('/api/ingest/documents')
      .then(function (resp) {
        if (!resp.ok) throw new Error('Failed to load documents');
        return resp.json();
      })
      .then(function (data) {
        var docs = data.documents || [];
        tbody.innerHTML = '';

        if (docs.length === 0) {
          var emptyRow = document.createElement('tr');
          emptyRow.className = 'doc-table-empty';
          emptyRow.innerHTML = '<td colspan="6" data-i18n="settings_no_documents">' +
            (translations['settings_no_documents'] || 'No documents uploaded yet.') + '</td>';
          tbody.appendChild(emptyRow);
          return;
        }

        docs.forEach(function (doc) {
          var row = document.createElement('tr');
          row.setAttribute('data-doc-id', doc.doc_id);

          var filenameCell = document.createElement('td');
          filenameCell.textContent = doc.filename || '';
          filenameCell.className = 'doc-filename';
          filenameCell.title = doc.filename || '';

          var typeCell = document.createElement('td');
          var ext = (doc.filename || '').split('.').pop().toUpperCase();
          typeCell.textContent = ext || '—';

          var chunksCell = document.createElement('td');
          chunksCell.textContent = String(doc.chunks_count || 0);

          var chunkSettingsCell = document.createElement('td');
          var cs = parseInt(doc.chunk_size) || 0;
          var co = parseInt(doc.chunk_overlap) || 0;
          if (cs > 0 && co > 0) {
            chunkSettingsCell.textContent = cs + ' / ' + co;
          } else if (cs > 0) {
            chunkSettingsCell.textContent = String(cs);
          } else {
            chunkSettingsCell.textContent = '\u2014';
          }

          var dateCell = document.createElement('td');
          dateCell.textContent = formatDateTime(doc.created_at);

          var actionsCell = document.createElement('td');

          var actionsWrapper = document.createElement('div');
          actionsWrapper.className = 'doc-actions-cell';

          // View button for chunk preview (AC-005.8)
          var viewBtn = document.createElement('button');
          viewBtn.className = 'btn-view-chunks';
          viewBtn.setAttribute('data-doc-id', doc.doc_id);
          viewBtn.textContent = '\u25B6 Chunks';
          viewBtn.title = translations['settings_view_chunks'] || 'View chunks';
          viewBtn.addEventListener('click', function() {
            toggleChunkPreview(this, doc.doc_id);
          });
          actionsWrapper.appendChild(viewBtn);

          var deleteBtn = document.createElement('button');
          deleteBtn.className = 'btn-delete-doc';
          deleteBtn.setAttribute('data-doc-id', doc.doc_id);
          deleteBtn.setAttribute('data-filename', doc.filename || '');
          deleteBtn.textContent = translations['settings_delete'] || 'Delete';
          deleteBtn.addEventListener('click', function () {
            var docId = this.getAttribute('data-doc-id');
            var fname = this.getAttribute('data-filename');
            var msg = fname;
            showConfirmModal(msg).then(function (confirmed) {
              if (confirmed) {
                deleteDocument(docId);
              }
            });
          });
          actionsWrapper.appendChild(deleteBtn);

          actionsCell.appendChild(actionsWrapper);

          row.appendChild(filenameCell);
          row.appendChild(typeCell);
          row.appendChild(chunksCell);
          row.appendChild(chunkSettingsCell);
          row.appendChild(dateCell);
          row.appendChild(actionsCell);
          tbody.appendChild(row);
        });
      })
      .catch(function (err) {
        console.error('Failed to load document list:', err);
      });
  }

  /**
   * Show a custom confirmation modal and return a Promise.
   * @param {string} message - The message to display
   * @returns {Promise<boolean>} Resolves to true if confirmed, false if cancelled
   */
  function showConfirmModal(message) {
    return new Promise(function (resolve) {
      var overlay = document.getElementById('confirmModal');
      var messageEl = document.getElementById('confirm-modal-message');
      var cancelBtn = document.getElementById('confirm-modal-cancel');
      var okBtn = document.getElementById('confirm-modal-ok');
      if (!overlay || !messageEl || !cancelBtn || !okBtn) {
        // Fallback to native confirm if modal HTML missing
        resolve(confirm(message));
        return;
      }

      messageEl.textContent = message;
      overlay.style.display = 'flex';

      // Focus the Cancel button by default (safe choice)
      cancelBtn.focus();

      function cleanup() {
        overlay.style.display = 'none';
        cancelBtn.removeEventListener('click', onCancel);
        okBtn.removeEventListener('click', onConfirm);
        document.removeEventListener('keydown', onKeyDown);
      }

      function onCancel() {
        cleanup();
        resolve(false);
      }

      function onConfirm() {
        cleanup();
        resolve(true);
      }

      function onKeyDown(e) {
        if (e.key === 'Escape') {
          e.preventDefault();
          onCancel();
        }
      }

      cancelBtn.addEventListener('click', onCancel);
      okBtn.addEventListener('click', onConfirm);
      document.addEventListener('keydown', onKeyDown);
    });
  }

  /**
   * Show the duplicate file modal and return a Promise resolving to the chosen action.
   * Returns {action: 'replace'|'cancel'|'rename', filename: string} or null if modal unavailable.
   * @param {File} file - The file that triggered the duplicate
   * @param {Object} dupData - The duplicate response from the server (409 Conflict)
   * @param {Element} progressItem - The progress item element to remove if cancelled
   * @returns {Promise<Object|null>} Resolves to {action, filename} or null
   */
  function showDuplicateModal(file, dupData, progressItem) {
    return new Promise(function (resolve) {
      var overlay = document.getElementById('duplicateModal');
      var filenameEl = document.getElementById('duplicate-filename');
      var existingChunksEl = document.getElementById('duplicate-existing-chunks');
      var existingSizeEl = document.getElementById('duplicate-existing-size');
      var existingSettingsEl = document.getElementById('duplicate-existing-settings');
      var newSizeEl = document.getElementById('duplicate-new-size');
      var estimatedChunksEl = document.getElementById('duplicate-estimated-chunks');
      var settingsWarning = document.getElementById('duplicate-settings-warning');
      var cancelBtn = document.getElementById('duplicate-modal-cancel');
      var renameBtn = document.getElementById('duplicate-modal-rename');
      var replaceBtn = document.getElementById('duplicate-modal-replace');

      if (!overlay) {
        // Modal HTML missing — fall through with cancel
        resolve(null);
        return;
      }

      // Helper: format bytes to human-readable size
      function fmtSize(bytes) {
        if (!bytes || bytes === 0) return '—';
        var kb = bytes / 1024;
        return kb >= 1024 ? (kb / 1024).toFixed(1) + ' MB' : Math.round(kb) + ' KB';
      }

      // Populate modal info
      if (filenameEl) filenameEl.textContent = dupData.filename || file.name;

      // Existing file column
      if (existingChunksEl) existingChunksEl.textContent = String(dupData.existing_chunks || 0);
      if (existingSizeEl) existingSizeEl.textContent = fmtSize(dupData.existing_size);
      if (existingSettingsEl) {
        var cs = dupData.stored_chunk_size || 512;
        var co = dupData.stored_chunk_overlap || 64;
        existingSettingsEl.textContent = cs + ' token, ' + co + ' overlap';
      }

      // New upload column
      if (newSizeEl) newSizeEl.textContent = fmtSize(dupData.new_file_size || file.size);
      if (estimatedChunksEl) estimatedChunksEl.textContent = String(dupData.estimated_chunks || 0);

      // Update new upload chunk settings (was previously hardcoded "512 token, 64 overlap")
      var newSettingsEl = document.getElementById('duplicate-new-settings');
      if (newSettingsEl) {
        var newCs = dupData.current_chunk_size || 512;
        var newCo = dupData.current_chunk_overlap || 64;
        newSettingsEl.textContent = newCs + ' token, ' + newCo + ' overlap';
      }

      if (settingsWarning) {
        settingsWarning.style.display = dupData.chunks_settings_changed ? 'block' : 'none';
      }

      overlay.style.display = 'flex';
      cancelBtn.focus();

      function cleanup() {
        overlay.style.display = 'none';
        cancelBtn.removeEventListener('click', onCancel);
        renameBtn.removeEventListener('click', onRename);
        replaceBtn.removeEventListener('click', onReplace);
        document.removeEventListener('keydown', onKeyDown);
      }

      function onCancel() {
        cleanup();
        if (progressItem && progressItem.parentNode) {
          progressItem.remove();
        }
        resolve({ action: 'cancel', filename: file.name });
      }

      function onRename() {
        cleanup();
        resolve({ action: 'rename', filename: file.name });
      }

      function onReplace() {
        cleanup();
        resolve({ action: 'replace', filename: file.name });
      }

      function onKeyDown(e) {
        if (e.key === 'Escape') {
          e.preventDefault();
          onCancel();
        }
      }

      cancelBtn.addEventListener('click', onCancel);
      renameBtn.addEventListener('click', onRename);
      replaceBtn.addEventListener('click', onReplace);
      document.addEventListener('keydown', onKeyDown);
    });
  }

  /**\n   * Delete a document by ID, then refresh the list.
   * @param {string} docId - The document ID to delete
   */
  function deleteDocument(docId) {
    fetch('/api/ingest/documents/' + docId, { method: 'DELETE' })
      .then(function (resp) {
        if (!resp.ok) throw new Error('Delete failed');
        return resp.json();
      })
      .then(function () {
        loadDocumentList();
      })
      .catch(function (err) {
        console.error('Failed to delete document:', err);
        alert('Failed to delete document: ' + (err.message || 'Unknown error'));
      });
  }

  /**
   * Toggle chunk preview for a document row (AC-005.8).
   * Fetches chunks from GET /api/ingest/documents/{doc_id}/chunks on first expand.
   * @param {Element} btn - The View/Hide button that was clicked
   * @param {string} docId - The document ID
   */
  function toggleChunkPreview(btn, docId) {
    var row = btn.closest('tr');
    if (!row) return;

    // Check if already expanded
    var existingChunkRow = row.nextElementSibling;
    if (existingChunkRow && existingChunkRow.classList.contains('chunk-row')) {
      // Collapse
      existingChunkRow.remove();
      btn.textContent = '\u25B6 Chunks';
      btn.title = translations['settings_view_chunks'] || 'View chunks';
      return;
    }

    // Expand: fetch chunks
    btn.textContent = '\u23F3';
    btn.title = translations['settings_loading'] || 'Loading...';

    fetch('/api/ingest/documents/' + encodeURIComponent(docId) + '/chunks')
      .then(function(resp) {
        if (!resp.ok) {
          throw new Error('Failed to fetch chunks: ' + resp.status);
        }
        return resp.json();
      })
      .then(function(chunks) {
        btn.textContent = '\u25BC Chunks';
        btn.title = translations['settings_hide_chunks'] || 'Hide chunks';
        renderChunkRow(row, chunks);
      })
      .catch(function(err) {
        console.error('Failed to fetch chunks:', err);
        btn.textContent = '\u25B6 Chunks';
        btn.title = translations['settings_view_chunks'] || 'View chunks';
      });
  }

  /**
   * Render chunk preview cards below a document row (AC-005.8).
   * @param {Element} docRow - The document table row
   * @param {Array} chunks - Array of chunk objects {chunk_index, text, token_count, page}
   */
  function renderChunkRow(docRow, chunks) {
    var chunkRow = document.createElement('tr');
    chunkRow.className = 'chunk-row';

    var chunkCell = document.createElement('td');
    chunkCell.colSpan = 6;

    var container = document.createElement('div');
    container.className = 'chunk-container';

    chunks.forEach(function(chunk) {
      var card = document.createElement('div');
      card.className = 'chunk-card';

      var header = document.createElement('div');
      header.className = 'chunk-card-header';

      var index = document.createElement('span');
      index.className = 'chunk-index';
      index.textContent = '#' + (chunk.chunk_index != null ? chunk.chunk_index : '?');

      var meta = document.createElement('span');
      meta.className = 'chunk-meta';
      var metaText = (chunk.token_count != null ? chunk.token_count : '?') + ' tokens';
      if (chunk.page != null) {
        metaText += ' \u00B7 Page ' + chunk.page;
      }
      meta.textContent = metaText;

      header.appendChild(index);
      header.appendChild(meta);

      var preview = document.createElement('div');
      preview.className = 'chunk-preview';
      var text = chunk.text || '';
      if (text.length > 200) {
        text = text.substring(0, 200) + '\u2026';
      }
      preview.textContent = text;

      card.appendChild(header);
      card.appendChild(preview);
      container.appendChild(card);
    });

    chunkCell.appendChild(container);
    chunkRow.appendChild(chunkCell);

    // Insert after the document row
    docRow.parentNode.insertBefore(chunkRow, docRow.nextSibling);
  }

  // ============================================================
  // Settings Page — LangSmith Modal
  // ============================================================

  /**
   * Initialize the LangSmith integration modal handlers.
   */
  function initLangSmithModal() {
    var connectBtn = document.getElementById('btn-connect-langsmith');
    var modal = document.getElementById('langsmithModal');
    if (!connectBtn || !modal) return; // Not on settings page

    var cancelBtn = document.getElementById('langsmith-cancel');
    var connectConfirmBtn = document.getElementById('langsmith-connect');

    // Show coming soon message
    connectBtn.addEventListener('click', function () {
      showToast(translations['settings_langsmith_coming_soon'] || 'LangSmith integration will be available in the next versions.');
    });

    // Cancel → hide modal
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () {
        modal.style.display = 'none';
      });
    }

    // Connect → show coming soon message
    if (connectConfirmBtn) {
      connectConfirmBtn.addEventListener('click', function () {
        showToast(translations['settings_langsmith_coming_soon'] || 'LangSmith integration will be available in the next versions.');
        modal.style.display = 'none';
      });
    }

    // Close modal on overlay click
    modal.addEventListener('click', function (e) {
      if (e.target === modal) {
        modal.style.display = 'none';
      }
    });
  }

  // ============================================================
  // Settings Page — System Prompt Reset & Locale Awareness
  // ============================================================

  /**
   * Initialize system prompt reset button and track manual edits.
   */
  function initSystemPromptReset() {
    var textarea = document.getElementById('settings-system-prompt');
    var resetBtn = document.getElementById('btn-reset-prompt');
    if (!textarea || !resetBtn) return; // Not on settings page

    // Track manual edits
    textarea.addEventListener('input', function () {
      systemPromptEdited = true;
      textarea.setAttribute('data-edited', 'true');
    });

    // Reset to default for current locale
    resetBtn.addEventListener('click', function () {
      var defaultPrompt = DEFAULT_SYSTEM_PROMPTS[currentLocale] || DEFAULT_SYSTEM_PROMPTS['en'];
      textarea.value = defaultPrompt;
      systemPromptEdited = false;
      textarea.removeAttribute('data-edited');

      // Show brief status under reset button
      var statusEl = document.getElementById('reset-prompt-status');
      if (statusEl) {
        statusEl.textContent = translations['settings_prompt_reset'] || 'Prompt reset to default.';
        statusEl.className = 'reset-prompt-status status-success';
        setTimeout(function () {
          statusEl.textContent = '';
          statusEl.className = 'reset-prompt-status';
        }, 2000);
      }
    });
  }

  // ============================================================
  // Toast Notification System
  // ============================================================

  /**
   * Show a non-disruptive toast notification.
   * @param {string} message - The message to display
   * @param {'info' | 'success' | 'warning' | 'error'} [type='info'] - Toast variant
   */
  function showToast(message, type) {
    if (type === undefined) type = 'info';

    var container = document.querySelector('.toast-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    var toast = document.createElement('div');
    toast.className = 'toast ' + type;

    var content = document.createElement('span');
    content.className = 'toast-content';
    content.textContent = message;
    toast.appendChild(content);

    var closeBtn = document.createElement('button');
    closeBtn.className = 'toast-close';
    closeBtn.textContent = '\u2715';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.addEventListener('click', function () {
      removeToast(toast);
    });
    toast.appendChild(closeBtn);

    container.appendChild(toast);

    // Auto-dismiss after 3.5 seconds
    var autoDismiss = setTimeout(function () {
      removeToast(toast);
    }, 3500);

    // Store the timeout so we can clear it on manual close
    toast._autoDismiss = autoDismiss;
  }

  /**
   * Remove a toast element with fade-out animation.
   * @param {HTMLElement} toast
   */
  function removeToast(toast) {
    if (toast._removing) return;
    toast._removing = true;

    if (toast._autoDismiss) {
      clearTimeout(toast._autoDismiss);
    }

    toast.classList.add('fade-out');
    setTimeout(function () {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 300);
  }

  // ============================================================
  // Bootstrap
  // ============================================================

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApp);
  } else {
    initializeApp();
  }

  // Cleanup on page unload
  window.addEventListener('beforeunload', function () {
    stopStatusPolling();
  });

  // Expose public API for testing and external use
  window.RAGStudio = {
    switchTab: switchTab,
    switchLanguage: switchLanguage,
    toggleMobileMenu: toggleMobileMenu,
    getCurrentTab: function () { return currentTab; },
    getCurrentLocale: function () { return currentLocale; }
  };
})();
