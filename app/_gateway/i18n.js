(function () {
  'use strict';

  /* ── engine ────────────────────────────────────────────── */
  var applying = false;
  var localeMap = [];
  var _rtf = null;   // Intl.RelativeTimeFormat instance for active locale

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

  /* ── relative time via Intl.RelativeTimeFormat ──────────── */
  // Maps English unit words (full + abbreviation) to Intl unit identifiers.
  // This is the only language-specific mapping needed — it parses the
  // English output that react-timeago (locale:'en') renders, then
  // Intl.RelativeTimeFormat handles translation to any target language.
  var ENG_UNIT = {
    'second': 'second', 'seconds': 'second',
    'sec': 'second', 'secs': 'second', 's': 'second',
    'minute': 'minute', 'minutes': 'minute',
    'min': 'minute', 'mins': 'minute', 'm': 'minute',
    'hour': 'hour', 'hours': 'hour',
    'hr': 'hour', 'hrs': 'hour', 'h': 'hour',
    'day': 'day', 'days': 'day', 'd': 'day',
    'week': 'week', 'weeks': 'week',
    'wk': 'week', 'wks': 'week', 'w': 'week',
    'month': 'month', 'months': 'month',
    'mo': 'month', 'mos': 'month',
    'year': 'year', 'years': 'year',
    'yr': 'year', 'yrs': 'year', 'y': 'year',
  };

  // Sort abbreviations longest-first so "wk" matches before "w", "min" before "m", etc.
  var ENG_ABBR = Object.keys(ENG_UNIT)
    .filter(function (k) { return k.length <= 4; })
    .sort(function (a, b) { return b.length - a.length; })
    .map(function (k) { return k.replace(/\./g, '\\.?'); })
    .join('|');

  function engUnit(raw) {
    var key = raw.toLowerCase().replace(/\./g, '');
    return ENG_UNIT[key] || ENG_UNIT[key.replace(/s$/, '')] || null;
  }

  function rtfFormat(n, unit) {
    return _rtf ? _rtf.format(n, unit) : '';
  }

  function translateRelativeTime(text) {
    if (!_rtf) return text;

    // "just now" → 0 seconds
    text = text.replace(/\bjust now\b/gi, rtfFormat(0, 'second'));

    // "a few seconds ago" → approximate -5 seconds
    text = text.replace(/\ba few seconds ago\b/gi, rtfFormat(-5, 'second'));

    // special-word forms
    text = text.replace(/\byesterday\b/gi, rtfFormat(-1, 'day'));
    text = text.replace(/\blast week\b/gi, rtfFormat(-1, 'week'));
    text = text.replace(/\blast month\b/gi, rtfFormat(-1, 'month'));
    text = text.replace(/\blast year\b/gi, rtfFormat(-1, 'year'));

    // "last/next" + abbreviated unit (e.g. "last wk.", "next mo.")
    text = text.replace(
      new RegExp('\\b(last|next)\\s+(' + ENG_ABBR + ')\\.?', 'gi'),
      function (m, direction, u) {
        var unit = engUnit(u) || 'day';
        var n = direction.toLowerCase() === 'last' ? -1 : 1;
        return rtfFormat(n, unit);
      }
    );

    // "X unit(s) ago" (with space, e.g. "5 minutes ago", "5 min. ago")
    text = text.replace(
      /(\d+)\s+([a-zA-Z]+\.?s?)\s+ago/gi,
      function (m, num, unit) {
        var u = engUnit(unit);
        return u ? rtfFormat(-parseInt(num, 10), u) : m;
      }
    );

    // compact narrow: "2d ago", "5min ago" (no space between number and unit)
    text = text.replace(
      /(\d+)([a-zA-Z]{1,4}\.?s?)\s+ago/gi,
      function (m, num, unit) {
        var u = engUnit(unit);
        return u ? rtfFormat(-parseInt(num, 10), u) : m;
      }
    );

    return text;
  }

  function walkReplace(root) {
    if (applying) return;
    if (!localeMap.length && !_rtf) return;

    sortLocaleMap();

    var iter = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var changes = [];
    var node;
    while ((node = iter.nextNode())) {
      if (!isRelevant(node)) continue;
      var text = node.nodeValue;
      var modified = false;

      if (localeMap.length) {
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
      }

      // Pass 2: relative time via Intl.RelativeTimeFormat
      if (_rtf) {
        var rt = translateRelativeTime(text);
        if (rt !== text) {
          text = rt;
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

  /* ── language detection ─────────────────────────────────── */
  var STORAGE_KEY = 'gotify-lang';

  // Normalises short/alias locale codes to the file name used on disk.
  var NORM = {
    'zh': 'zh_CN',
    'zh-cn': 'zh_CN', 'zh-sg': 'zh_CN',
    'zh-hans': 'zh_CN', 'zh-hans-cn': 'zh_CN', 'zh-hans-sg': 'zh_CN',
    'fr': 'fr', 'fr-fr': 'fr', 'fr-ca': 'fr', 'fr-ch': 'fr', 'fr-be': 'fr',
    'de': 'de', 'de-de': 'de', 'de-at': 'de', 'de-ch': 'de',
    'es': 'es', 'es-es': 'es', 'es-mx': 'es', 'es-ar': 'es',
    'pt': 'pt', 'pt-pt': 'pt', 'pt-br': 'pt',
    'ru': 'ru', 'ru-ru': 'ru',
    'it': 'it', 'it-it': 'it', 'it-ch': 'it',
    'ko': 'ko', 'ko-kr': 'ko',
    'ja': 'ja', 'ja-jp': 'ja',
  };

  function detectLang() {
    var m = window.location.search.match(/[?&]lang=([^&]+)/);
    if (m) return NORM[m[1].toLowerCase()] || m[1];
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return saved;
    } catch (e) {}
    try {
      var raw = (navigator.language || navigator.userLanguage || '').toLowerCase();
      if (raw.indexOf('zh') === 0) return 'zh_CN';
      if (raw.indexOf('de') === 0) return 'de';
      if (raw.indexOf('fr') === 0) return 'fr';
      if (raw.indexOf('es') === 0) return 'es';
      if (raw.indexOf('pt') === 0) return 'pt';
      if (raw.indexOf('ru') === 0) return 'ru';
      if (raw.indexOf('it') === 0) return 'it';
      if (raw.indexOf('ko') === 0) return 'ko';
      if (raw.indexOf('ja') === 0) return 'ja';
    } catch (e) {}
    return 'en';
  }

  /* ── helper: safe Intl.RelativeTimeFormat creation ──────── */
  function createRtf(lang) {
    try {
      _rtf = new Intl.RelativeTimeFormat(lang.replace(/_/g, '-'), { numeric: 'auto' });
    } catch (e) {
      _rtf = null;
    }
  }

  /* ── public API (called by enhance.js) ─────────────────── */
  window.__i18n = {
    walkReplace: walkReplace,
    detectLang: detectLang,

    activate: function (lang) {
      // Prevent CJK wrapping in table headers
      var css = document.createElement('style');
      css.textContent = 'th.MuiTableCell-head,.MuiTableCell-head{white-space:nowrap!important}';
      document.head.appendChild(css);

      if (window.__LOCALE_MAP) {
        localeMap = window.__LOCALE_MAP;
        createRtf(lang);
        if (document.body) walkReplace(document.body);
        return;
      }
      var script = document.createElement('script');
      script.src = '/_gateway/lang/' + lang + '.js';
      script.onload = function () {
        localeMap = window.__LOCALE_MAP || [];
        createRtf(lang);
        if (document.body) walkReplace(document.body);
      };
      script.onerror = function () {
        console.warn('Gotify locale not found: ' + lang);
        _rtf = null;
        try { localStorage.removeItem('gotify-lang'); } catch (e) {}
      };
      document.head.appendChild(script);
    }
  };
})();
