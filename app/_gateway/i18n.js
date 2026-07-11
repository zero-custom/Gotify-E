(function () {
  'use strict';

  var STORAGE_KEY = 'gotify-lang';

  /* ── navigator.language → locale key ──────────────────── */
  var LANG_MAP = {
    'zh-CN': 'zh_CN', 'zh-SG': 'zh_CN',
    'zh':    'zh_CN',
    'zh-Hans': 'zh_CN', 'zh-Hans-CN': 'zh_CN',
    'zh-Hans-SG': 'zh_CN',
  };
  function navLang() {
    try {
      var raw = (navigator.language || navigator.userLanguage || '').toLowerCase();
      // direct match
      if (LANG_MAP[raw]) return LANG_MAP[raw];
      // prefix match (e.g. 'zh' -> zh_CN, 'en' -> en, 'de' -> en)
      var prefix = raw.split('-')[0];
      return LANG_MAP[prefix] || (prefix === 'en' ? 'en' : null);
    } catch (e) { return null; }
  }

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
    var nav = navLang();
    if (nav) return nav;
    return 'en';
  }

  var lang = detectLang();
  if (!lang || lang === 'en') return;

  // Prevent CJK wrapping in table headers. Chinese characters are individually
  // breakable in CSS, so "优先级" wraps to three lines in narrow columns.
  var css = document.createElement('style');
  css.textContent = 'th.MuiTableCell-head,.MuiTableCell-head{white-space:nowrap!important}';
  document.head.appendChild(css);

  /* ── engine ────────────────────────────────────────────── */
  var applying = false;
  var localeMap = [];

  // Skip text inside elements that contain user data
  function isDataContainer(el) {
    if (!el) return false;
    var tag = el.tagName;
    // Skip INPUT, TEXTAREA, SELECT, OPTION (user input values)
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'OPTION') return true;
    // Skip <td> (table data cells = user data) but allow <th> (table headers = labels)
    if (tag === 'TD') return true;
    // Skip elements with explicit notranslate class
    var cl = el.className || '';
    if (typeof cl === 'string' && cl.indexOf('notranslate') !== -1) return true;
    return false;
  }

  function isRelevant(node) {
    if (!node.nodeValue) return false;
    var parent = node.parentElement;
    if (!parent) return false;
    var tag = parent.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE') return false;
    // Check if any ancestor is a data container
    var el = parent;
    while (el) {
      if (isDataContainer(el)) return false;
      el = el.parentElement;
    }
    return true;
  }

  // Sort locale map: longest strings first to avoid partial replacement
  function sortLocaleMap() {
    localeMap.sort(function (a, b) { return b[0].length - a[0].length; });
  }

  // Whole-word match: replace only when 'en' appears as a whole word
  function wholeWordReplace(text, en, zh) {
    // Escape special regex chars in the source string
    var esc = en.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // Match as whole word: preceded by non-word char or start, followed by non-word char or end
    var re = new RegExp('(^|[^a-zA-Z])' + esc + '($|[^a-zA-Z])', 'g');
    return text.replace(re, function (match, before, after) {
      return before + zh + after;
    });
  }

  function walkReplace(root) {
    if (applying || !localeMap.length) return;

    sortLocaleMap();

    var iter = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var changes = [];
    var node;
    while ((node = iter.nextNode())) {
      if (!isRelevant(node)) continue;
      var text = node.nodeValue;
      var modified = false;
      for (var i = 0; i < localeMap.length; i++) {
        var en = localeMap[i][0];
        var zh = localeMap[i][1];
        if (text.indexOf(en) !== -1) {
          var newText = wholeWordReplace(text, en, zh);
          if (newText !== text) {
            text = newText;
            modified = true;
          }
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

  function brandGotify() {
    var h5s = document.querySelectorAll('h5');
    for (var i = 0; i < h5s.length; i++) {
      if (h5s[i].textContent.trim() === 'Gotify') {
        h5s[i].innerHTML = 'Gotify<sup style="font-size:.6em">[E]</sup>';
        return;
      }
    }
  }

  function startObserver() {
    walkReplace(document.body);
    brandGotify();
    var observer = new MutationObserver(function () {
      walkReplace(document.body);
      brandGotify();
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
