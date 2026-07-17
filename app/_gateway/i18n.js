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
      if (LANG_MAP[raw]) return LANG_MAP[raw];
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

  // Prevent CJK wrapping in table headers
  var css = document.createElement('style');
  css.textContent = 'th.MuiTableCell-head,.MuiTableCell-head{white-space:nowrap!important}';
  document.head.appendChild(css);

  /* ── engine ────────────────────────────────────────────── */
  var applying = false;
  var localeMap = [];

  function isDataContainer(el) {
    if (!el) return false;
    var tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'OPTION') return true;
    if (tag === 'TD') return true;
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
    var el = parent;
    while (el) {
      if (isDataContainer(el)) return false;
      el = el.parentElement;
    }
    return true;
  }

  function sortLocaleMap() {
    localeMap.sort(function (a, b) { return b[0].length - a[0].length; });
  }

  function wholeWordReplace(text, en, zh) {
    var esc = en.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    var re = new RegExp('(^|[^a-zA-Z])' + esc + '($|[^a-zA-Z])', 'g');
    return text.replace(re, function (match, before, after) {
      return before + zh + after;
    });
  }

  /* ── relative time (Intl.RelativeTimeFormat) ──────────── */
  // react-timeago on the backend uses locale:'en', so browser renders
  // English relative times like "5 minutes ago", "1 hour ago", etc.
  // We catch them via regex since the numeric value varies.  This only works
  // for <TimeAgo /> nodes that have already rendered; the MutationObserver
  // re-applies when React re-renders (e.g. ticking to the next minute).

  var UNIT_LONG = {
    'second': '秒', 'seconds': '秒',
    'minute': '分钟', 'minutes': '分钟',
    'hour': '小时', 'hours': '小时',
    'day': '天', 'days': '天',
    'week': '周', 'weeks': '周',
    'month': '个月', 'months': '个月',
    'year': '年', 'years': '年',
  };

  // narrow style abbreviations used by Intl.RelativeTimeFormat('en',{style:'narrow'})
  var UNIT_NARROW = {
    's': '秒', 'sec': '秒',
    'm': '分钟', 'min': '分钟',
    'h': '小时', 'hr': '小时',
    'd': '天',
    'w': '周', 'wk': '周',
    'mo': '个月',
    'y': '年', 'yr': '年',
  };

  // Build a regex that matches a period-abbreviated unit and optionally
  // a trailing 's': "min.", "min", "mins.", "mins" etc.
  var NARROW_UNIT_SRC = Object.keys(UNIT_NARROW)
    .map(function (u) { return u.replace(/\./g, '\\.?'); })
    .join('|');

  function translateRelativeTime(text) {
    // exact special forms (numeric: 'auto')
    text = text.replace(/\bjust now\b/gi, '刚刚');
    text = text.replace(/\ba few seconds ago\b/gi, '几秒前');
    text = text.replace(/\byesterday\b/gi, '昨天');
    text = text.replace(/\blast week\b/gi, '上周');
    text = text.replace(/\blast month\b/gi, '上个月');
    text = text.replace(/\blast year\b/gi, '去年');
    text = text.replace(/\btomorrow\b/gi, '明天');
    text = text.replace(/\bnext week\b/gi, '下周');
    text = text.replace(/\bnext month\b/gi, '下个月');
    text = text.replace(/\bnext year\b/gi, '明年');

    // "X unit(s) ago" (long style, e.g. "5 minutes ago")
    text = text.replace(
      /(\d+)\s+(seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago/gi,
      function (m, n, u) {
        return n + ' ' + (UNIT_LONG[u.toLowerCase()] || u) + '前';
      }
    );

    // "X unit(s) ago" (narrow style, e.g. "5 min. ago", "1 wk. ago")
    text = text.replace(
      new RegExp('(\\d+)\\s+(' + NARROW_UNIT_SRC + ')\\.?s?\\s+ago', 'gi'),
      function (m, n, u) {
        var key = u.toLowerCase().replace(/\./g, '');
        return n + ' ' + (UNIT_NARROW[key] || u) + '前';
      }
    );

    // "Xunit ago" (compact narrow style, e.g. "2d ago", "4w ago")
    // Matches when the number directly abuts the unit abbreviation.
    text = text.replace(
      new RegExp('(\\d+)(' + NARROW_UNIT_SRC + ')\\.?s?\\s+ago', 'gi'),
      function (m, n, u) {
        var key = u.toLowerCase().replace(/\./g, '');
        return n + ' ' + (UNIT_NARROW[key] || u) + '前';
      }
    );

    // "in X unit(s)" (long style future, e.g. "in 5 minutes")
    text = text.replace(
      /in\s+(\d+)\s+(seconds?|minutes?|hours?|days?|weeks?|months?|years?)/gi,
      function (m, n, u) {
        return n + ' ' + (UNIT_LONG[u.toLowerCase()] || u) + '后';
      }
    );

    // "in X unit(s)" (narrow style future, e.g. "in 5 min.")
    text = text.replace(
      new RegExp('in\\s+(\\d+)\\s+(' + NARROW_UNIT_SRC + ')\\.?s?', 'gi'),
      function (m, n, u) {
        var key = u.toLowerCase().replace(/\./g, '');
        return n + ' ' + (UNIT_NARROW[key] || u) + '后';
      }
    );

    return text;
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

      // Pass 1: literal whole-word map replacements
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

      // Pass 2: regex-based relative time translation
      var rt = translateRelativeTime(text);
      if (rt !== text) {
        text = rt;
        modified = true;
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
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
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
