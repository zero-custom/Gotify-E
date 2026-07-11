(function () {
  'use strict';

  var STORAGE_KEY = 'gotify-lang';

  /* ── lang detection ───────────────────────────────────── */
  function detectLang() {
    var m = window.location.search.match(/[?&]lang=([^&]+)/);
    if (m) {
      var lang = m[1];
      try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) {}
      return lang;
    }
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return saved;
    } catch (e) {}
    return 'en';
  }

  var lang = detectLang();
  if (!lang || lang === 'en') return;

  /* ── engine ────────────────────────────────────────────── */
  var applying = false;
  var localeMap = [];

  function isRelevant(node) {
    if (!node.nodeValue) return false;
    var parent = node.parentElement;
    if (!parent) return false;
    var tag = parent.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE') return false;
    return true;
  }

  function walkReplace(root) {
    if (applying || !localeMap.length) return;

    var iter = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var changes = [];
    var node;
    while ((node = iter.nextNode())) {
      if (!isRelevant(node)) continue;
      var text = node.nodeValue;
      var modified = false;
      for (var i = 0; i < localeMap.length; i++) {
        if (text.indexOf(localeMap[i][0]) !== -1) {
          if (!modified) {
            text = text.split(localeMap[i][0]).join(localeMap[i][1]);
          } else {
            node.nodeValue = node.nodeValue.replace(localeMap[i][0], localeMap[i][1]);
          }
          modified = true;
        }
      }
      if (modified) changes.push([node, text]);
    }

    if (changes.length) {
      applying = true;
      for (var j = 0; j < changes.length; j++) {
        changes[j][0].nodeValue = changes[j][1];
      }
      applying = false;
    }
  }

  function startObserver() {
    walkReplace(document.body);
    var observer = new MutationObserver(function () {
      walkReplace(document.body);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  /* ── load locale ──────────────────────────────────────── */
  var script = document.createElement('script');
  script.src = '/_gateway/' + lang + '.js';
  script.onload = function () {
    localeMap = window.__LOCALE_MAP || [];
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        setTimeout(startObserver, 400);
      });
    } else {
      setTimeout(startObserver, 400);
    }
  };
  script.onerror = function () {
    console.warn('Gotify locale not found: ' + lang);
    try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
  };
  document.head.appendChild(script);
})();
