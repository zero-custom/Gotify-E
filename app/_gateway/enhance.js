(function () {
  'use strict';

  /* ── brand ──────────────────────────────────────────────── */
  function brandGotify() {
    var h5s = document.querySelectorAll('h5');
    for (var i = 0; i < h5s.length; i++) {
      if (h5s[i].textContent.trim() === 'Gotify') {
        h5s[i].innerHTML = 'Gotify<sup style="font-size:.6em">[E]</sup>';
        return;
      }
    }
  }

  /* ── layout optimisation ─────────────────────────────────── */
  // Override DefaultPage inner <main> max-width (700px default) for wider screens.
  function injectLayoutCSS() {
    if (document.getElementById('_ge_layout')) return;
    var css = document.createElement('style');
    css.id = '_ge_layout';
    css.textContent = 'main > main{max-width:50vw!important}';
    document.head.appendChild(css);
  }

  /* ── absolute / relative time toggle ───────────────────── */
  var TIME_MODE_KEY = 'gotify_e_time_mode';
  var timeMode = (function () {
    try { return localStorage.getItem(TIME_MODE_KEY) || 'relative'; }
    catch (e) { return 'relative'; }
  })();

  function i18nLang() {
    return (window.__i18n && window.__i18n.detectLang()) || 'en';
  }

  function localeTag() {
    return i18nLang().replace(/_/g, '-');
  }

  function formatAbsoluteTime(dateStr) {
    try {
      var d = new Date(dateStr);
      if (isNaN(d.getTime())) return '';
      return d.toLocaleString(localeTag(), {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
      });
    } catch (e) { return ''; }
  }

  function convertTimeElements(root) {
    if (timeMode !== 'absolute') return;
    var times = root.querySelectorAll('time[datetime]');
    for (var i = 0; i < times.length; i++) {
      var el = times[i];
      var text = el.textContent;
      var datetime = el.getAttribute('datetime');
      if (!text || !datetime) continue;
      var abs = formatAbsoluteTime(datetime);
      if (!abs || text === abs) continue;  // already absolute or unparseable
      el.setAttribute('data-gotify-relative', text);
      el.textContent = abs;
    }
  }

  function restoreRelativeTimes() {
    var times = document.querySelectorAll('time[data-gotify-relative]');
    for (var i = 0; i < times.length; i++) {
      var el = times[i];
      var orig = el.getAttribute('data-gotify-relative');
      if (orig) el.textContent = orig;
      el.removeAttribute('data-gotify-relative');
    }
  }

  function syncToggleStyle() {
    var toggle = document.querySelector('.gotify-e-time-toggle');
    if (!toggle) return;
    var btn = document.getElementById('refresh-all') || document.getElementById('delete-all');
    if (!btn) return;
    var s = window.getComputedStyle(btn);
    if (s.backgroundColor === 'rgba(0, 0, 0, 0.12)' || s.backgroundColor === 'rgba(0, 0, 0, 0)') return;
    var muiClass = btn.className;
    if (toggle.className !== muiClass + ' gotify-e-time-toggle') {
      toggle.className = muiClass + ' gotify-e-time-toggle';
    }
  }

  function isChineseLang() {
    return i18nLang().indexOf('zh') === 0;
  }

  function toggleTimeLabel(isAbs) {
    return isChineseLang()
      ? (isAbs ? '绝对时间' : '相对时间')
      : (isAbs ? 'Absolute Time' : 'Relative Time');
  }

  function injectTimeToggle() {
    var refreshBtn = document.getElementById('refresh-all');
    if (!refreshBtn) return;
    var toolbar = refreshBtn.parentElement;
    if (!toolbar) return;
    if (toolbar.querySelector('.gotify-e-time-toggle')) return;

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'gotify-e-time-toggle';
    toggle.style.marginRight = '5px';
    toggle.textContent = toggleTimeLabel(timeMode === 'absolute');
    toggle.onclick = function () {
      timeMode = timeMode === 'absolute' ? 'relative' : 'absolute';
      try { localStorage.setItem(TIME_MODE_KEY, timeMode); } catch (ex) {}
      toggle.textContent = toggleTimeLabel(timeMode === 'absolute');
      if (timeMode === 'absolute') {
        convertTimeElements(document.body);
      } else {
        restoreRelativeTimes();
      }
    };
    toolbar.insertBefore(toggle, refreshBtn);
    syncToggleStyle();
  }

  function activateI18nIfNeeded() {
    if (!window.__i18n) return;
    try {
      var lang = window.__i18n.detectLang();
      if (lang && lang !== 'en') {
        window.__i18n.activate(lang);
      }
    } catch (e) {
      // i18n init failure must not block enhance features
    }
  }

  /* ── single MutationObserver: translation + enhance ────── */
  var applying = false;

  function tick() {
    if (applying) return;
    applying = true;
    try {
      if (window.__i18n && window.__i18n.walkReplace) {
        window.__i18n.walkReplace(document.body);
      }
      brandGotify();
      injectTimeToggle();
      syncToggleStyle();
      convertTimeElements(document.body);
    } finally {
      applying = false;
    }
  }

  function startObserver() {
    tick();

    var observer = new MutationObserver(function () {
      tick();
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  /* ── enhance.js boot: inject layout CSS, detect lang, activate i18n if needed, start observer ── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      injectLayoutCSS();
      activateI18nIfNeeded();
      setTimeout(startObserver, 400);
    });
  } else {
    injectLayoutCSS();
    activateI18nIfNeeded();
    setTimeout(startObserver, 400);
  }
})();
