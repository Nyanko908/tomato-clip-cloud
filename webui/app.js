/* Tomato Clip — chat frontend. Python(pywebview)がwindow.chatUIの各関数を呼んでUIを更新する。 */
(function () {
  "use strict";

  var AI_AVATAR =
    '<img class="ai-avatar" src="logo.png" alt="" aria-hidden="true">';

  var el = {
    scroll: document.getElementById("scroll"),
    welcome: document.getElementById("welcome"),
    thread: document.getElementById("thread"),
    field: document.getElementById("field"),
    send: document.getElementById("send"),
    convList: document.getElementById("convList"),
    accPlan: document.getElementById("accPlan"),
  };

  var started = false;   // 会話が始まったか（welcome→thread）
  var busy = false;      // 送信中

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function linkify(s) {
    return esc(s).replace(/(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>');
  }
  // 最小Markdown: **太字** / *斜体* / `code` / URL / # 見出し / - * 箇条書き。
  // まずescしてから記号を変換するのでXML安全。
  function mdInline(t) {
    t = esc(t);
    t = t.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    t = t.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    t = t.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    return t;
  }
  function mdToHtml(text) {
    var lines = String(text == null ? "" : text).split(/\r?\n/);
    var out = [], para = [], listOpen = false;
    function flushPara() { if (para.length) { out.push('<div class="md-p">' + para.join("<br>") + "</div>"); para = []; } }
    function closeList() { if (listOpen) { out.push("</ul>"); listOpen = false; } }
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i], m;
      if ((m = ln.match(/^\s*[-*]\s+(.*)$/))) {
        flushPara();
        if (!listOpen) { out.push('<ul class="md-ul">'); listOpen = true; }
        out.push("<li>" + mdInline(m[1]) + "</li>");
      } else if ((m = ln.match(/^\s*(#{1,3})\s+(.*)$/))) {
        flushPara(); closeList();
        out.push('<div class="md-h md-h' + m[1].length + '">' + mdInline(m[2]) + "</div>");
      } else if (ln.trim() === "") {
        flushPara(); closeList();
      } else {
        closeList(); para.push(mdInline(ln));
      }
    }
    flushPara(); closeList();
    return out.join("");
  }
  function scrollBottom() { el.scroll.scrollTop = el.scroll.scrollHeight; }

  function ensureThread() {
    if (!started) {
      started = true;
      el.welcome.style.display = "none";
      el.thread.style.display = "flex";
    }
  }

  // ---- render helpers (Pythonからも呼ばれる) ----
  var chatUI = {
    addUser: function (text) {
      ensureThread();
      var d = document.createElement("div");
      d.className = "msg user";
      d.innerHTML = '<div class="bubble">' + esc(text) + "</div>";
      el.thread.appendChild(d);
      scrollBottom();
    },

    // AIのテキスト。同じ「ターン」に追記したい場合は append=true
    addAiText: function (text, append) {
      ensureThread();
      var body;
      if (append) {
        var last = el.thread.querySelector(".msg.ai:last-child .ai-body .txt");
        if (last) { last.innerHTML += mdToHtml(text); scrollBottom(); return; }
      }
      var d = document.createElement("div");
      d.className = "msg ai";
      d.innerHTML = AI_AVATAR + '<div class="ai-body"><div class="txt md">' + mdToHtml(text) + "</div></div>";
      el.thread.appendChild(d);
      scrollBottom();
    },

    thinking: function (on) {
      var ex = document.getElementById("thinking");
      if (on) {
        if (ex) return;
        ensureThread();
        var d = document.createElement("div");
        d.id = "thinking"; d.className = "msg ai";
        d.innerHTML = AI_AVATAR + '<div class="ai-body"><div class="txt" style="color:var(--faint)">考え中<span class="spinner" style="display:inline-block;vertical-align:-2px;margin-left:6px"></span></div></div>';
        el.thread.appendChild(d); scrollBottom();
      } else if (ex) { ex.remove(); }
    },

    startProgress: function (id, title) {
      ensureThread();
      chatUI.thinking(false);
      var d = document.createElement("div");
      d.className = "msg ai";
      d.innerHTML = AI_AVATAR +
        '<div class="ai-body"><div class="card" id="' + id + '">' +
        '<div class="hd"><span class="spinner"></span><span class="ttl">' + esc(title || "生成中…") + "</span></div>" +
        '<div class="step">準備しています…</div></div></div>';
      el.thread.appendChild(d); scrollBottom();
    },
    updateProgress: function (id, stepText) {
      var c = document.getElementById(id);
      if (!c) return;
      var s = c.querySelector(".step");
      if (s) s.textContent = stepText;
      scrollBottom();
    },
    finishProgress: function (id, title) {
      var c = document.getElementById(id);
      if (!c) return;
      c.classList.add("done");
      var hd = c.querySelector(".hd");
      if (hd) hd.innerHTML = '<span class="check">✓</span><span class="ttl">' + esc(title || "完了") + "</span>";
    },

    addVideoCard: function (dataJson) {
      ensureThread();
      var v = typeof dataJson === "string" ? JSON.parse(dataJson) : dataJson;
      var raw = String(v.path || "").replace(/\\/g, "/");
      // クラウドWeb版はサーバー配信の絶対URL(/media/... や http...)を渡す＝そのまま使う。
      // デスクトップ版はローカルパス(C:/...)＝file:/// を前置（従来通り）。
      var src = (/^(https?:)?\/\//.test(raw) || raw.charAt(0) === "/") ? raw : "file:///" + raw;
      var d = document.createElement("div");
      d.className = "msg ai";
      d.innerHTML = AI_AVATAR +
        '<div class="ai-body"><div class="vcard">' +
        '<video src="' + esc(src) + '" controls playsinline preload="metadata"></video>' +
        '<div class="meta"><div class="vtitle">' + esc(v.title || "完成した動画") + "</div>" +
        '<div class="vsub">' + esc(v.subtitle || "") + "</div>" +
        '<div class="acts">' +
        '<button class="btn primary" onclick="chatUI.post(\'' + esc(v.path) + '\')">YouTube に投稿</button>' +
        '<button class="btn" onclick="chatUI.openFile(\'' + esc(v.path) + '\')">フォルダで開く</button>' +
        "</div></div></div></div>";
      el.thread.appendChild(d); scrollBottom();
    },

    addError: function (text) {
      chatUI.thinking(false);
      chatUI.addAiText("⚠️ " + text);
    },

    setPlan: function (t) { if (el.accPlan) el.accPlan.textContent = t; },

    // ---- 会話履歴（サイドバー） ----
    _activeCid: null,
    refreshConvs: function () {
      var a = api(); if (!a || !a.list_conversations) return;
      a.list_conversations().then(function (list) {
        try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (e) {}
        renderConvs(list || []);
      }).catch(function () {});
    },
    openConversation: function (cid) {
      if (busy) return;
      chatUI.closeSearch && chatUI.closeSearch();
      chatUI.closeStats && chatUI.closeStats();
      chatUI.closeSchedule && chatUI.closeSchedule();
      chatUI.closeCloud && chatUI.closeCloud();
      var a = api(); if (!a || !a.load_conversation) return;
      a.load_conversation(cid).then(function (d) {
        try { d = typeof d === "string" ? JSON.parse(d) : d; } catch (e) {}
        if (!d || !d.ok) return;
        chatUI._activeCid = cid;
        chatUI._firstTitleSet = true;
        chatUI.replay(d.messages || []);
        chatUI.refreshConvs();
      }).catch(function () {});
    },
    replay: function (messages) {
      el.thread.innerHTML = "";
      started = true;
      el.welcome.style.display = "none";
      el.thread.style.display = "flex";
      (messages || []).forEach(function (m) {
        if (m.kind === "user") chatUI.addUser(m.text || "");
        else if (m.kind === "ai") chatUI.addAiText(m.text || "");
        else if (m.kind === "video") chatUI.addVideoCard(m.data || {});
      });
      scrollBottom();
    },

    // ---- user actions ----
    chip: function (prefix) {
      el.field.value = prefix;
      el.field.focus();
      autogrow();
      if (!/[:：]\s*$/.test(prefix)) doSend();  // URLチップは入力待ち、それ以外は即送信
    },
    // 提案チップ（要素経由）。data-prompt（i18nで言語化された送信文）を使う。
    chipEl: function (btn) {
      var prefix = (btn && (btn.dataset.prompt || btn.getAttribute("data-i18n-prompt"))) || "";
      chatUI.chip(prefix);
    },
    newChat: function () {
      if (busy) return;
      chatUI.closeSearch && chatUI.closeSearch();
      chatUI.closeStats && chatUI.closeStats();
      chatUI.closeSchedule && chatUI.closeSchedule();
      chatUI.closeCloud && chatUI.closeCloud();
      el.thread.innerHTML = "";
      el.thread.style.display = "none";
      el.welcome.style.display = "flex";
      started = false;
      chatUI._activeCid = null;
      chatUI._firstTitleSet = false;
      if (window.pywebview && window.pywebview.api) window.pywebview.api.new_conversation();
      chatUI.refreshConvs();
    },
    post: function (path) { if (window.pywebview) window.pywebview.api.post_video(path); },
    openFile: function (path) { if (window.pywebview) window.pywebview.api.open_file(path); },
  };
  window.chatUI = chatUI;

  // ---- サイドバー開閉 ----
  chatUI.setSidebar = function (collapsed) {
    var app = document.querySelector(".app");
    if (!app) return;
    app.classList.toggle("sidebar-collapsed", !!collapsed);
    try { localStorage.setItem("tc_sidebar_collapsed", collapsed ? "1" : "0"); } catch (e) {}
  };
  chatUI.toggleSidebar = function () {
    var app = document.querySelector(".app");
    chatUI.setSidebar(!(app && app.classList.contains("sidebar-collapsed")));
  };
  (function restoreSidebar() {
    try {
      if (localStorage.getItem("tc_sidebar_collapsed") === "1") {
        var app = document.querySelector(".app");
        if (app) app.classList.add("sidebar-collapsed");
      }
    } catch (e) {}
  })();

  // サイドバーの会話履歴リストを描画（各行クリックで復元）
  function renderConvs(list) {
    if (!el.convList) return;
    el.convList.innerHTML = "";
    list.forEach(function (c) {
      var b = document.createElement("button");
      b.className = "conv" + (c.id === chatUI._activeCid ? " on" : "");
      b.textContent = c.title || "会話";
      b.title = c.title || "";
      b.addEventListener("click", function () { chatUI.openConversation(c.id); });
      el.convList.appendChild(b);
    });
  }

  // ================= 設定 / 初回セットアップ =================
  var LANGS = [["ja", "日本語"], ["en", "English"], ["es", "Español"], ["pt", "Português"],
    ["de", "Deutsch"], ["fr", "Français"], ["id", "Bahasa Indonesia"], ["hi", "हिन्दी"],
    ["ko", "한국어"], ["it", "Italiano"], ["tr", "Türkçe"], ["nl", "Nederlands"]];
  var api = function () { return (window.pywebview && window.pywebview.api) || null; };
  // 翻訳ヘルパ（動的メッセージ用。未収録は原文）
  chatUI.t = function (k) { return (window.__i18n && window.__i18n[k]) || k; };

  function buildLangSelect(sel, current) {
    if (!sel) return;
    sel.innerHTML = "";
    LANGS.forEach(function (l) {
      var o = document.createElement("option");
      o.value = l[0]; o.textContent = l[1];
      if (l[0] === current) o.selected = true;
      sel.appendChild(o);
    });
  }
  function seg(id, ok, msg) {
    var e = document.getElementById(id);
    if (!e) return;
    e.className = "seg" + (ok === true ? " ok" : ok === false ? " ng" : "");
    e.textContent = msg || "";
  }
  function showModal(id) {
    ["modalSettings", "modalOnboard", "modalLegal", "modalPlugin"].forEach(function (m) {
      var el2 = document.getElementById(m); if (el2) el2.style.display = (m === id ? "block" : "none");
    });
    document.getElementById("overlay").classList.add("on");
  }

  chatUI.closeOverlay = function () { document.getElementById("overlay").classList.remove("on"); };

  // クラウド／プラグイン タブ（現状は案内モーダル。プラグインはクラウド版でのみ動作）
  chatUI.openPlugins = function () { showModal("modalPlugin"); };

  // ================= クラウド セットアップ（イントロ → 起動） =================
  var _cloudTermTimer = null;
  chatUI.closeCloud = function () {
    var p = document.getElementById("cloudPanel"); if (p) p.style.display = "none";
    if (_cloudTermTimer) { clearInterval(_cloudTermTimer); _cloudTermTimer = null; }
  };
  chatUI.openCloud = function () {
    chatUI.closeOverlay && chatUI.closeOverlay();
    chatUI.closeSearch && chatUI.closeSearch();
    chatUI.closeStats && chatUI.closeStats();
    chatUI.closeSchedule && chatUI.closeSchedule();
    cloudShowScreen("A");
    var p = document.getElementById("cloudPanel"); if (p) p.style.display = "flex";
    refreshCloudStatus();
  };
  function refreshCloudStatus() {
    var a = api(); var box = document.getElementById("cloudStatus");
    if (!a || !box || !a.cloud_server_state) return;
    a.cloud_server_state().then(function (s) {
      try { s = typeof s === "string" ? JSON.parse(s) : s; } catch (e) {}
      s = s || {};
      if (s.logged_in && s.url) {
        box.style.display = "flex";
        box.innerHTML = '<span class="dot ' + (s.online ? "on" : "off") + '"></span>' +
          (s.online ? chatUI.t("あなたのクラウドが稼働中です") : chatUI.t("クラウドは現在オフラインです")) +
          '<a href="#" onclick="chatUI.cloudOpen(\'' + esc(s.url) + '\');return false;">' + chatUI.t("開く") + " ›</a>";
      } else {
        box.style.display = "none";
      }
    }).catch(function () {});
  }
  function cloudShowScreen(which) {
    var a = document.getElementById("cloudScreenA"), b = document.getElementById("cloudScreenB");
    if (a) a.style.display = (which === "A" ? "flex" : "none");
    if (b) b.style.display = (which === "B" ? "flex" : "none");
    if (which === "B") startCloudTermAnim();
    else if (_cloudTermTimer) { clearInterval(_cloudTermTimer); _cloudTermTimer = null; }
  }
  chatUI.cloudGoLaunch = function () { cloudShowScreen("B"); };
  chatUI.cloudBack = function () { cloudShowScreen("A"); };

  // 黒いターミナル風の「セットアップしてる感」アニメ（ダミーのタイプ演出をループ）
  function startCloudTermAnim() {
    var body = document.getElementById("cloudTermBody");
    if (!body) return;
    if (_cloudTermTimer) { clearInterval(_cloudTermTimer); _cloudTermTimer = null; }
    var script = [
      { t: "$ ", c: "t", txt: "tomato-clip cloud setup", cls: "" },
      { t: "", c: "", txt: "" },
      { t: "› ", c: "g", txt: "設定を同期しています…", cls: "d" },
      { t: "  ✓ ", c: "g", txt: "Gemini APIキー", cls: "" },
      { t: "  ✓ ", c: "g", txt: "YouTube 連携", cls: "" },
      { t: "  ✓ ", c: "g", txt: "チャンネル設定", cls: "" },
      { t: "› ", c: "g", txt: "暗号バンドルを生成…", cls: "d" },
      { t: "  ", c: "", txt: "TOMATO_BUNDLE ████████████", cls: "d" },
      { t: "› ", c: "g", txt: "準備完了。クリックで開始 ▶", cls: "" },
    ];
    var i = 0, ch = 0, lines = [];
    body.innerHTML = "";
    function tick() {
      if (i >= script.length) { i = 0; ch = 0; lines = []; setTimeout(function () { if (_cloudTermTimer) body.innerHTML = ""; }, 900); return; }
      var s = script[i];
      var full = s.txt;
      if (ch === 0) lines.push({ pre: s.t, cls: s.c, txt: "" });
      ch++;
      lines[lines.length - 1].txt = full.slice(0, ch);
      var html = lines.map(function (l) {
        return '<div class="ln"><span class="' + (l.pre === "$ " ? "t" : "g") + '">' + esc(l.pre) + '</span>' +
          '<span class="' + (l.cls || "") + '">' + esc(l.txt) + "</span></div>";
      }).join("");
      body.innerHTML = html + '<div class="ln"><span class="cur"></span></div>';
      if (ch >= full.length) { i++; ch = 0; }
    }
    _cloudTermTimer = setInterval(tick, 55);
  }

  chatUI.cloudLaunch = function () {
    var a = api();
    seg("cloudLaunchSeg", null, chatUI.t("セットアップウィンドウを起動しています…"));
    if (!a || !a.cloud_launch_setup) { seg("cloudLaunchSeg", false, chatUI.t("この環境では起動できません")); return; }
    a.cloud_launch_setup().then(function (r) {
      try { r = typeof r === "string" ? JSON.parse(r) : r; } catch (e) {}
      r = r || {};
      seg("cloudLaunchSeg", !!r.ok, r.ok
        ? ("✓ " + chatUI.t("別ウィンドウでセットアップを開きました。画面の指示に従ってください。"))
        : ("✕ " + chatUI.t("起動できませんでした") + (r.message ? " (" + r.message + ")" : "")));
    }).catch(function (e) { seg("cloudLaunchSeg", false, "✕ " + String(e)); });
  };

  // ---- アカウント（クレジット円周リング＋ホバーメニュー） ----
  chatUI.setCredits = function (plan, credits, max) {
    var ring = document.getElementById("avatarRing");
    var line = document.getElementById("acctCredit");
    if (plan === "pro") {
      // Pro = 無制限：グラデーションの満円リング
      if (ring) {
        ring.style.background = "conic-gradient(from 0deg, #e5503c, #f6b73c, #3aa552, #3b82f6, #e5503c)";
        ring.title = "Pro";
      }
      if (line) line.innerHTML = "<b>Pro</b> · " + chatUI.t("無制限");
    } else {
      var c = (credits == null) ? 0 : credits, m = max || 20;
      var deg = Math.round((m ? Math.max(0, Math.min(1, c / m)) : 0) * 360);
      if (ring) {
        ring.style.background = "conic-gradient(var(--tomato) " + deg + "deg, var(--line) " + deg + "deg)";
        ring.title = chatUI.t("クレジット") + " " + c + " / " + m;
      }
      if (line) line.innerHTML = chatUI.t("クレジット") + " <b>" + c + "</b> / " + m;
    }
  };
  chatUI.refreshAccount = function () {
    var a = api(); if (!a || !a.get_account_state) return;
    a.get_account_state().then(function (st) {
      try { st = typeof st === "string" ? JSON.parse(st) : st; } catch (e) {}
      st = st || {};
      chatUI.setPlan(st.plan === "pro" ? "Pro" : chatUI.t("デモモード"));
      chatUI.setCredits(st.plan, st.credits, st.credit_max);
    }).catch(function () {});
  };

  // ---- TomatoAI アカウント（Google ログイン） ----
  chatUI.refreshAccountLogin = function () {
    var a = api(); if (!a || !a.account_state) return;
    a.account_state().then(function (s) {
      try { s = typeof s === "string" ? JSON.parse(s) : s; } catch (e) {}
      applyAccountLogin(s || {});
    }).catch(function () {});
  };
  function applyAccountLogin(s) {
    var lbl = document.getElementById("acctLoginLabel");
    var item = document.getElementById("acctLoginItem");
    var whoName = document.querySelector(".side-account .who b");
    var whoSub = document.getElementById("accPlan");
    var av = document.querySelector(".side-account .avatar");
    if (s.logged_in) {
      if (lbl) lbl.textContent = chatUI.t("ログアウト");
      if (item) item.onclick = function () { chatUI.accountLogout(); };
      // 連携チャンネルがあればそれを、無ければメール名を表示
      if (whoName) whoName.textContent = s.channel_title || (s.email ? s.email.split("@")[0] : "");
      if (whoSub) whoSub.textContent = s.channel_title ? s.email : (whoSub.textContent || "");
      if (av) av.textContent = (s.channel_title || s.email || "?").charAt(0).toUpperCase();
    } else {
      if (lbl) lbl.textContent = chatUI.t("ログイン");
      if (item) item.onclick = function () { chatUI.accountLogin(); };
    }
  }
  chatUI.accountLogin = function () {
    var a = api(); if (!a || !a.account_login) return;
    var lbl = document.getElementById("acctLoginLabel");
    if (lbl) lbl.textContent = chatUI.t("ブラウザでログイン中…");
    a.account_login();  // 完了は accountResult（poll）で受ける
  };
  chatUI.accountLogout = function () {
    var a = api(); if (!a || !a.account_logout) return;
    a.account_logout().then(function () { chatUI.refreshAccountLogin(); });
  };
  // Python から poll 経由で呼ばれる（ログイン完了/失敗）
  chatUI.accountResult = function (r) {
    r = r || {};
    if (r.ok) chatUI.refreshAccountLogin();
    else {
      var lbl = document.getElementById("acctLoginLabel");
      if (lbl) lbl.textContent = chatUI.t("ログイン");
    }
  };
  // ================= スケジュール（週間タイムライン・DnD） =================
  var HOURS = [0, 3, 6, 9, 12, 15, 18, 21];   // 3時間刻み8枠
  var WDAY = ["月", "火", "水", "木", "金", "土", "日"];
  var _schedWeekStart = null;   // その週の月曜0時
  var _schedTasks = [];

  function mondayOf(d) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var wd = (x.getDay() + 6) % 7;   // 月=0
    x.setDate(x.getDate() - wd);
    return x;
  }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function localISO(dt) {   // タイムゾーンずれを避けてローカルISO（秒まで）
    return dt.getFullYear() + "-" + pad2(dt.getMonth() + 1) + "-" + pad2(dt.getDate()) +
      "T" + pad2(dt.getHours()) + ":" + pad2(dt.getMinutes()) + ":00";
  }

  chatUI.closeSchedule = function () {
    var p = document.getElementById("schedulePanel"); if (p) p.style.display = "none";
  };
  chatUI.openSchedule = function () {
    chatUI.closeSearch && chatUI.closeSearch();
    chatUI.closeStats && chatUI.closeStats();
    chatUI.closeCloud && chatUI.closeCloud();
    var p = document.getElementById("schedulePanel"); if (p) p.style.display = "flex";
    if (!_schedWeekStart) _schedWeekStart = mondayOf(new Date());
    wirePalette();
    loadSchedule();
  };
  chatUI.schedWeek = function (dir) {
    if (!_schedWeekStart) _schedWeekStart = mondayOf(new Date());
    if (dir === 0) _schedWeekStart = mondayOf(new Date());
    else _schedWeekStart = new Date(_schedWeekStart.getTime() + dir * 7 * 864e5);
    renderWeek();
  };

  function loadSchedule() {
    var a = api();
    if (!a || !a.list_schedule) { _schedTasks = []; renderWeek(); return; }
    a.list_schedule().then(function (list) {
      try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (e) {}
      _schedTasks = list || [];
      renderWeek();
    }).catch(function () { _schedTasks = []; renderWeek(); });
  }

  function slotIndexForHour(h) {   // 時刻→最も近い下の枠index
    var idx = 0;
    for (var i = 0; i < HOURS.length; i++) if (h >= HOURS[i]) idx = i;
    return idx;
  }

  function renderWeek() {
    var grid = document.getElementById("schedGrid");
    if (!grid || !_schedWeekStart) return;
    var ws = _schedWeekStart;
    var end = new Date(ws.getTime() + 6 * 864e5);
    var lbl = document.getElementById("schedWeekLabel");
    if (lbl) lbl.textContent = (ws.getMonth() + 1) + "/" + ws.getDate() + " – " + (end.getMonth() + 1) + "/" + end.getDate();
    var now = new Date();
    var todayKey = now.getFullYear() + "-" + now.getMonth() + "-" + now.getDate();

    // header
    var head = "<thead><tr><th></th>";
    for (var d = 0; d < 7; d++) {
      var day = new Date(ws.getTime() + d * 864e5);
      var isToday = (day.getFullYear() + "-" + day.getMonth() + "-" + day.getDate()) === todayKey;
      head += '<th class="' + (isToday ? "today" : "") + '">' + WDAY[d] +
        '<div class="th-d">' + day.getDate() + "</div></th>";
    }
    head += "</tr></thead>";

    // body: task lookup by cell
    var byCell = {};
    _schedTasks.forEach(function (t) {
      var dt = new Date(t.run_at);
      if (isNaN(dt)) return;
      var dcol = Math.floor((new Date(dt.getFullYear(), dt.getMonth(), dt.getDate()) - ws) / 864e5);
      if (dcol < 0 || dcol > 6) return;
      var row = slotIndexForHour(dt.getHours());
      (byCell[dcol + "_" + row] = byCell[dcol + "_" + row] || []).push(t);
    });

    var body = "<tbody>";
    for (var r = 0; r < HOURS.length; r++) {
      body += "<tr><td class='timecol'>" + pad2(HOURS[r]) + ":00</td>";
      for (var c = 0; c < 7; c++) {
        var cellDate = new Date(ws.getTime() + c * 864e5);
        cellDate.setHours(HOURS[r], 0, 0, 0);
        var isPast = cellDate.getTime() < now.getTime() - 60000;
        var cards = (byCell[c + "_" + r] || []).map(function (t) {
          var rep = t.repeat ? ' rep" title="' + (t.repeat === "daily" ? "毎日" : "毎週") + '"' : '"';
          return '<div class="scard' + (t.repeat ? " rep" : "") + '" draggable="true" data-tid="' + t.id + '">' +
            "🎬" + esc(String(t.count)) + (t.repeat ? "🔁" : "") +
            '<span class="x" data-cancel="' + t.id + '">✕</span></div>';
        }).join("");
        body += '<td class="' + (isPast ? "past" : "") + '" data-col="' + c + '" data-row="' + r + '">' + cards + "</td>";
      }
      body += "</tr>";
    }
    body += "</tbody>";
    grid.innerHTML = head + body;
    wireGridDnD();
  }

  function cellDateTime(col, row) {
    var dt = new Date(_schedWeekStart.getTime() + col * 864e5);
    dt.setHours(HOURS[row], 0, 0, 0);
    return dt;
  }

  var _dragCount = null, _dragTaskId = null;
  function wirePalette() {
    var chips = document.querySelectorAll("#schedulePanel .pchip");
    for (var i = 0; i < chips.length; i++) {
      var ch = chips[i];
      if (ch._wired) continue;
      ch._wired = true;
      ch.addEventListener("dragstart", function (e) {
        _dragCount = parseInt(this.getAttribute("data-count"), 10) || 1;
        _dragTaskId = null;
        try { e.dataTransfer.setData("text/plain", "chip"); e.dataTransfer.effectAllowed = "copy"; } catch (x) {}
      });
    }
  }
  function wireGridDnD() {
    var grid = document.getElementById("schedGrid");
    if (!grid) return;
    // 既存カードの drag（移動）と ✕（削除）
    grid.querySelectorAll(".scard").forEach(function (card) {
      card.addEventListener("dragstart", function (e) {
        _dragTaskId = parseInt(this.getAttribute("data-tid"), 10);
        _dragCount = null;
        try { e.dataTransfer.setData("text/plain", "card"); e.dataTransfer.effectAllowed = "move"; } catch (x) {}
        e.stopPropagation();
      });
    });
    grid.querySelectorAll("[data-cancel]").forEach(function (x) {
      x.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = parseInt(this.getAttribute("data-cancel"), 10);
        var a = api(); if (a && a.cancel_schedule) a.cancel_schedule(id).then(function (list) {
          try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (er) {}
          _schedTasks = list || []; renderWeek();
        });
      });
    });
    // セルの drop 受け
    grid.querySelectorAll("td[data-col]").forEach(function (td) {
      td.addEventListener("dragover", function (e) {
        if (td.classList.contains("past")) return;
        e.preventDefault(); td.classList.add("dragover");
      });
      td.addEventListener("dragleave", function () { td.classList.remove("dragover"); });
      td.addEventListener("drop", function (e) {
        e.preventDefault(); td.classList.remove("dragover");
        if (td.classList.contains("past")) return;
        var col = parseInt(td.getAttribute("data-col"), 10);
        var row = parseInt(td.getAttribute("data-row"), 10);
        var iso = localISO(cellDateTime(col, row));
        var a = api(); if (!a) return;
        var after = function (list) {
          try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (er) {}
          if (list && !list.error) { _schedTasks = list; renderWeek(); }
        };
        if (_dragTaskId != null && a.reschedule) {
          a.reschedule(_dragTaskId, iso).then(after);
        } else if (_dragCount != null && a.add_schedule) {
          a.add_schedule(iso, _dragCount, null).then(after);
        }
        _dragCount = null; _dragTaskId = null;
      });
    });
  }

  // ================= 統計ダッシュボード（YouTube Data API v3・Studio風） =================
  function nfmt(n) {
    n = Number(n) || 0;
    if (n >= 1e8) return (n / 1e8).toFixed(1).replace(/\.0$/, "") + "億";
    if (n >= 1e4) return (n / 1e4).toFixed(1).replace(/\.0$/, "") + "万";
    return n.toLocaleString();
  }
  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return "";
    return (d.getMonth() + 1) + "/" + d.getDate();
  }
  function setTxt(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }

  chatUI.closeStats = function () {
    var p = document.getElementById("statsPanel"); if (p) p.style.display = "none";
  };
  chatUI.openStats = function () {
    var p = document.getElementById("statsPanel"); if (p) p.style.display = "flex";
    chatUI.closeSearch && chatUI.closeSearch();
    chatUI.closeSchedule && chatUI.closeSchedule();
    chatUI.closeCloud && chatUI.closeCloud();
    loadDashboard(false);
  };
  chatUI.refreshDashboard = function () { loadDashboard(true); };

  function loadDashboard(force) {
    var a = api();
    var loading = document.getElementById("dashLoading");
    var content = document.getElementById("dashContent");
    var errBox = document.getElementById("dashError");
    if (loading) loading.style.display = "block";
    if (content) content.style.display = "none";
    if (errBox) errBox.style.display = "none";
    if (!a || !a.get_youtube_dashboard) { showDashError({ error: "no_key" }); return; }
    a.get_youtube_dashboard(!!force).then(function (d) {
      try { d = typeof d === "string" ? JSON.parse(d) : d; } catch (e) {}
      d = d || {};
      if (loading) loading.style.display = "none";
      if (d.error) { showDashError(d); return; }
      renderDashboard(d);
    }).catch(function (e) {
      if (loading) loading.style.display = "none";
      showDashError({ error: "api", message: String(e) });
    });
  }

  function showDashError(d) {
    var content = document.getElementById("dashContent");
    var errBox = document.getElementById("dashError");
    if (content) content.style.display = "none";
    if (!errBox) return;
    var msg;
    if (d.error === "no_key")
      msg = chatUI.t("YouTube APIキーが未設定です。設定から登録してください。");
    else if (d.error === "no_channel")
      msg = chatUI.t("チャンネルIDが未設定です。設定でチャンネルを登録してください。");
    else if (d.error === "channel_not_found")
      msg = chatUI.t("チャンネルが見つかりませんでした。IDをご確認ください。");
    else
      msg = chatUI.t("統計の取得に失敗しました。") + (d.message ? " (" + d.message + ")" : "");
    errBox.innerHTML = esc(msg) +
      '<div><button class="btn" onclick="chatUI.openSettings&&chatUI.openSettings()" data-i18n="設定を開く">' +
      chatUI.t("設定を開く") + "</button></div>";
    errBox.style.display = "block";
  }

  function renderDashboard(d) {
    var content = document.getElementById("dashContent");
    if (content) content.style.display = "block";
    var ch = d.channel || {}, t = d.totals || {};
    var thumb = document.getElementById("dashThumb");
    if (thumb) thumb.src = ch.thumbnail || "";
    setTxt("dashTitle", ch.title || "—");
    setTxt("dashUpdated", chatUI.t("更新") + ": " + (d.generated_at || "").replace("T", " "));
    setTxt("dashSubs", nfmt(t.subs));
    setTxt("dashViews", nfmt(t.views));
    setTxt("dashVideos", nfmt(t.video_count));
    setTxt("dashEng", ((t.avg_engagement || 0) * 100).toFixed(1) + "%");

    // 成長折れ線（登録者）
    var line = document.getElementById("dashLine");
    var ts = d.timeseries || [];
    if (line) {
      if (ts.length < 2) {
        line.innerHTML = '<div class="dash-empty-chart">' +
          chatUI.t("推移は日々自動で記録されます（数日後にグラフになります）。") + "</div>";
      } else {
        line.innerHTML = lineChartSVG(ts.map(function (p) {
          return { x: fmtDate(p.date), y: p.subs };
        }));
      }
    }
    // トップ動画 横棒
    var bar = document.getElementById("dashBar");
    if (bar) {
      var top = d.top || [];
      if (!top.length) {
        bar.innerHTML = '<div class="dash-empty-chart">' + chatUI.t("まだ投稿がありません。") + "</div>";
      } else {
        bar.innerHTML = barChartSVG(top.map(function (v) {
          return { label: v.title, value: v.views };
        }));
      }
    }
    // 動画テーブル
    renderVideoTable(d.videos || []);
  }

  function renderVideoTable(videos) {
    var tbl = document.getElementById("dashTable");
    if (!tbl) return;
    if (!videos.length) {
      tbl.innerHTML = '<tr><td class="dash-empty">' + chatUI.t("まだ投稿がありません。") + "</td></tr>";
      return;
    }
    var head = "<thead><tr>" +
      '<th class="l" data-i18n="動画">' + chatUI.t("動画") + "</th>" +
      '<th data-i18n="公開日">' + chatUI.t("公開日") + "</th>" +
      '<th data-i18n="再生">' + chatUI.t("再生") + "</th>" +
      '<th data-i18n="高評価">' + chatUI.t("高評価") + "</th>" +
      '<th data-i18n="コメント">' + chatUI.t("コメント") + "</th>" +
      '<th data-i18n="エンゲージ率">' + chatUI.t("エンゲージ率") + "</th></tr></thead>";
    var rows = videos.map(function (v) {
      return "<tr>" +
        '<td class="l"><div class="dash-vid">' +
        (v.thumbnail ? '<img src="' + esc(v.thumbnail) + '" alt="">' : "") +
        "<span>" + esc(v.title || "") + "</span></div></td>" +
        "<td>" + esc(fmtFullDate(v.published)) + "</td>" +
        "<td>" + nfmt(v.views) + "</td>" +
        "<td>" + nfmt(v.likes) + "</td>" +
        "<td>" + nfmt(v.comments) + "</td>" +
        "<td>" + ((v.engagement || 0) * 100).toFixed(1) + "%</td></tr>";
    }).join("");
    tbl.innerHTML = head + "<tbody>" + rows + "</tbody>";
  }
  function fmtFullDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return "";
    return d.getFullYear() + "/" + (d.getMonth() + 1) + "/" + d.getDate();
  }

  // ---- SVG チャート（外部ライブラリ非依存・単一系列トマト色） ----
  function lineChartSVG(points) {
    var W = 440, H = 180, pad = { l: 40, r: 12, t: 12, b: 24 };
    var iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
    var ys = points.map(function (p) { return p.y; });
    var ymax = Math.max.apply(null, ys), ymin = Math.min.apply(null, ys);
    if (ymax === ymin) { ymax += 1; ymin = Math.max(0, ymin - 1); }
    var n = points.length;
    var X = function (i) { return pad.l + (n === 1 ? iw / 2 : (i / (n - 1)) * iw); };
    var Y = function (v) { return pad.t + ih - ((v - ymin) / (ymax - ymin)) * ih; };
    var d = "", area = "";
    points.forEach(function (p, i) { d += (i ? "L" : "M") + X(i) + " " + Y(p.y) + " "; });
    area = d + "L" + X(n - 1) + " " + (pad.t + ih) + " L" + X(0) + " " + (pad.t + ih) + " Z";
    var grid = "", labelsY = "";
    for (var g = 0; g <= 2; g++) {
      var gy = pad.t + (ih / 2) * g, gv = Math.round(ymax - ((ymax - ymin) / 2) * g);
      grid += '<line class="grid" x1="' + pad.l + '" y1="' + gy + '" x2="' + (W - pad.r) + '" y2="' + gy + '"/>';
      labelsY += '<text class="axis" x="' + (pad.l - 6) + '" y="' + (gy + 3) + '" text-anchor="end">' + nfmt(gv) + "</text>";
    }
    var dots = "", xlab = "", hits = "";
    points.forEach(function (p, i) {
      dots += '<circle class="dot" cx="' + X(i) + '" cy="' + Y(p.y) + '" r="3"><title>' +
        esc(p.x) + ": " + nfmt(p.y) + "</title></circle>";
      if (n <= 8 || i % Math.ceil(n / 8) === 0)
        xlab += '<text class="axis" x="' + X(i) + '" y="' + (H - 6) + '" text-anchor="middle">' + esc(p.x) + "</text>";
    });
    return '<svg class="dchart" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet">' +
      grid + labelsY + '<path class="area" d="' + area + '"/><path class="line" d="' + d + '"/>' +
      dots + xlab + "</svg>";
  }

  function barChartSVG(items) {
    var W = 440, rowH = 46, padT = 6;   // 1行=ラベル(上)＋バー＋値。
    var H = padT + items.length * rowH;
    var vmax = Math.max.apply(null, items.map(function (it) { return it.value; })) || 1;
    var barMaxW = W - 16 - 64;
    var rows = items.map(function (it, i) {
      var top = padT + i * rowH;
      var barY = top + 18;
      var w = Math.max(2, (it.value / vmax) * barMaxW);
      var label = (it.label || "").length > 30 ? it.label.slice(0, 30) + "…" : (it.label || "");
      return "<g>" +
        '<text class="barlbl" x="8" y="' + (top + 12) + '">' + esc(label) + "</text>" +
        '<rect class="bar" x="8" y="' + barY + '" width="' + w + '" height="12" rx="4">' +
        "<title>" + esc(it.label || "") + ": " + nfmt(it.value) + "</title></rect>" +
        '<text class="barval" x="' + (8 + w + 6) + '" y="' + (barY + 10) + '">' + nfmt(it.value) + "</text></g>";
    }).join("");
    return '<svg class="dchart" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet">' +
      rows + "</svg>";
  }

  // ---- 会話検索（タイトル＋本文を横断） ----
  function hl(text, q) {
    var e = esc(text || "");
    var qq = esc((q || "").trim());
    if (!qq) return e;
    var re = new RegExp("(" + qq.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
    return e.replace(re, "<mark>$1</mark>");
  }
  function dateLabel(ts) {
    if (!ts) return "";
    var d = new Date(ts * 1000), now = new Date();
    var startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    var t = d.getTime();
    if (t >= startToday) return chatUI.t("今日");
    if (t >= startToday - 864e5) return chatUI.t("昨日");
    return (d.getMonth() + 1) + "月" + d.getDate() + "日";
  }
  function renderSearchResults(list, q) {
    var box = document.getElementById("searchResults");
    var label = document.getElementById("searchLabel");
    if (!box) return;
    if (label) {
      label.textContent = q ? chatUI.t("検索結果") : chatUI.t("最近");
      label.style.display = (!q && (!list || !list.length)) ? "none" : "block";
    }
    if (!list || !list.length) {
      box.innerHTML = '<div class="search-empty">' +
        (q ? chatUI.t("一致する会話がありません") : chatUI.t("まだ会話がありません")) + "</div>";
      return;
    }
    box.innerHTML = "";
    list.forEach(function (c) {
      var b = document.createElement("button");
      b.className = "sresult";
      var snip = c.snippet ? '<div class="ss">' + hl(c.snippet, q) + "</div>" : "";
      b.innerHTML = '<div class="st-main"><div class="st">' + hl(c.title || "会話", q) + "</div>" + snip +
        '</div><div class="sdate">' + esc(dateLabel(c.updated)) + "</div>";
      b.addEventListener("click", function () {
        chatUI.closeSearch();
        chatUI.openConversation(c.id);
      });
      box.appendChild(b);
    });
  }
  function runSearch(q) {
    var a = api(); if (!a) return;
    q = (q || "").trim();
    if (!q) {   // 空欄は最近の会話を表示
      if (a.list_conversations) a.list_conversations().then(function (list) {
        try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (e) {}
        renderSearchResults((list || []).map(function (c) {
          return { id: c.id, title: c.title, snippet: "", updated: c.updated };
        }), "");
      }).catch(function () {});
      return;
    }
    if (a.search_conversations) a.search_conversations(q).then(function (list) {
      try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (e) {}
      renderSearchResults(list || [], q);
    }).catch(function () {});
  }
  chatUI.openSearch = function () {
    chatUI.closeStats && chatUI.closeStats();
    chatUI.closeSchedule && chatUI.closeSchedule();
    chatUI.closeCloud && chatUI.closeCloud();
    var panel = document.getElementById("searchPanel");
    if (panel) panel.style.display = "flex";
    var inp = document.getElementById("searchInput");
    if (inp) {
      inp.value = "";
      setTimeout(function () { inp.focus(); }, 50);
      if (!inp._wired) {
        inp._wired = true;
        var timer;
        inp.addEventListener("input", function () {
          clearTimeout(timer);
          var v = inp.value;
          timer = setTimeout(function () { runSearch(v); }, 180);
        });
        inp.addEventListener("keydown", function (e) {
          if (e.key === "Escape") chatUI.closeSearch();
        });
      }
    }
    runSearch("");
  };
  chatUI.closeSearch = function () {
    var panel = document.getElementById("searchPanel");
    if (panel) panel.style.display = "none";
  };

  // 自動生成タイトルが確定したら（Python→_js経由）サイドバーを更新
  chatUI.renameConversation = function () { chatUI.refreshConvs(); };

  chatUI.openSettings = function () {
    var a = api(); if (!a || !a.get_settings) { showModal("modalSettings"); return; }
    a.get_settings().then(function (s) {
      try { s = typeof s === "string" ? JSON.parse(s) : s; } catch (e) {}
      s = s || {};
      var g = document.getElementById("setGemini"); if (g) g.value = s.gemini_key || "";
      var y = document.getElementById("setYoutube"); if (y) y.value = s.youtube_key || "";
      buildLangSelect(document.getElementById("setUiLang"), s.ui_lang || "ja");
      var pb = document.getElementById("setPlan");
      if (pb) pb.textContent = (s.plan === "pro") ? "Pro" : (chatUI.t("デモモード"));
      var cr = document.getElementById("setCredits");
      if (cr) cr.textContent = (s.plan === "pro") ? "" : ((s.credits != null) ? ("💳 " + s.credits + " / " + (s.credit_max || 20)) : "");
      seg("stGemini", null, ""); seg("stYoutube", null, ""); seg("stSave", null, "");
      seg("stLicense", null, ""); seg("stPromo", null, "");
      showModal("modalSettings");
    }).catch(function () { showModal("modalSettings"); });
  };

  chatUI.testKey = function (kind, scope) {
    var a = api(); if (!a) return;
    var inId = (scope === "ob" ? "ob" : "set") + (kind === "gemini" ? "Gemini" : "Youtube");
    var stId = (scope === "ob" ? "stOb" : "st") + (kind === "gemini" ? "Gemini" : "Youtube");
    var val = (document.getElementById(inId) || {}).value || "";
    seg(stId, null, "…");
    a.test_api_key(kind, val).then(function (r) {
      try { r = typeof r === "string" ? JSON.parse(r) : r; } catch (e) {}
      r = r || {};
      seg(stId, !!r.ok, (r.ok ? "✓ " + chatUI.t("接続できました") : "✕ " + chatUI.t("接続できませんでした")));
    }).catch(function () { seg(stId, false, "✕ " + chatUI.t("接続できませんでした")); });
  };

  chatUI.saveKeys = function () {
    var a = api(); if (!a) return;
    var g = (document.getElementById("setGemini") || {}).value || "";
    var y = (document.getElementById("setYoutube") || {}).value || "";
    a.save_api_keys(g, y, "", "").then(function () { seg("stSave", true, "✓ " + chatUI.t("保存しました")); });
  };

  chatUI.changeLang = function (lang) {
    var a = api();
    if (a && a.set_ui_lang) a.set_ui_lang(lang);
    applyLang(lang);
    // 両方のセレクトを同期
    var s1 = document.getElementById("setUiLang"); if (s1) s1.value = lang;
    var s2 = document.getElementById("obUiLang"); if (s2) s2.value = lang;
  };

  chatUI.activate = function () {
    var a = api(); if (!a) return;
    var key = (document.getElementById("setLicense") || {}).value || "";
    seg("stLicense", null, "…");
    a.activate_license(key).then(function (r) {
      try { r = typeof r === "string" ? JSON.parse(r) : r; } catch (e) {}
      r = r || {};
      seg("stLicense", !!r.ok, (r.ok ? "✓ " : "✕ ") + (r.message || ""));
      if (r.ok) {
        var pb = document.getElementById("setPlan"); if (pb) pb.textContent = (r.plan === "pro") ? "Pro" : chatUI.t("デモモード");
        chatUI.setPlan((r.plan === "pro") ? "Pro" : chatUI.t("デモモード"));
        var cr = document.getElementById("setCredits"); if (cr && r.plan === "pro") cr.textContent = "";
        chatUI.refreshAccount();
      }
    }).catch(function () { seg("stLicense", false, "✕"); });
  };

  chatUI.promo = function () {
    var a = api(); if (!a) return;
    var code = (document.getElementById("setPromo") || {}).value || "";
    seg("stPromo", null, "…");
    a.apply_promo(code).then(function (r) {
      try { r = typeof r === "string" ? JSON.parse(r) : r; } catch (e) {}
      r = r || {};
      if (r.status === "ok") {
        seg("stPromo", true, "✓ +" + (r.credits || 0) + (r.total != null ? (" (→ " + r.total + ")") : ""));
        var cr = document.getElementById("setCredits");
        if (cr && r.total != null) cr.textContent = "💳 " + r.total;
        chatUI.refreshAccount();
      } else {
        seg("stPromo", false, "✕ " + (r.message || r.status || ""));
      }
    }).catch(function () { seg("stPromo", false, "✕"); });
  };

  chatUI.showLegal = function (kind) {
    var a = api();
    chatUI._legalReturn = document.getElementById("modalOnboard").style.display === "block" ? "modalOnboard" : "modalSettings";
    var lang = document.documentElement.lang || "ja";
    document.getElementById("legalTitle").textContent = chatUI.t(kind === "terms" ? "利用規約" : "プライバシーポリシー");
    var body = document.getElementById("legalBody");
    body.innerHTML = "…";
    if (!a || !a.get_legal_text) return;
    a.get_legal_text(kind, lang).then(function (d) {
      try { d = typeof d === "string" ? JSON.parse(d) : d; } catch (e) {}
      d = d || {}; var html = "";
      if (d.updated) html += '<p style="color:var(--faint)">' + esc(d.updated) + "</p>";
      (d.sections || []).forEach(function (s) {
        html += "<h4>" + esc(s[0]) + "</h4><p>" + esc(s[1]) + "</p>";
      });
      body.innerHTML = html || "—";
      showModal("modalLegal");
    });
  };
  chatUI.backFromLegal = function () { showModal(chatUI._legalReturn || "modalSettings"); };

  // ---- 初回セットアップ ----
  chatUI.startOnboard = function (state) {
    buildLangSelect(document.getElementById("obUiLang"), (state && state.ui_lang) || document.documentElement.lang || "ja");
    chatUI.obValidate();
    showModal("modalOnboard");
  };
  chatUI.obValidate = function () {
    var g = ((document.getElementById("obGemini") || {}).value || "").trim();
    var agreed = (document.getElementById("obAgree") || {}).checked;
    var btn = document.getElementById("obStart");
    if (btn) btn.disabled = !(g && agreed);
  };
  chatUI.finishOnboard = function () {
    var a = api(); if (!a) return;
    var g = ((document.getElementById("obGemini") || {}).value || "").trim();
    var y = ((document.getElementById("obYoutube") || {}).value || "").trim();
    var lang = (document.getElementById("obUiLang") || {}).value || "ja";
    var btn = document.getElementById("obStart"); if (btn) btn.disabled = true;
    a.save_api_keys(g, y, "", "").then(function () {
      return a.agree_terms(lang, lang);
    }).then(function () {
      chatUI.closeOverlay();
      chatUI.setPlan(chatUI.t("デモモード"));
    }).catch(function () { if (btn) btn.disabled = false; });
  };

  // ---- sending ----
  function setBusy(b) {
    busy = b;
    el.send.disabled = b;
  }
  function doSend() {
    var text = el.field.value.trim();
    if (!text || busy) return;
    chatUI.addUser(text);
    chatUI._firstTitleSet = true;
    el.field.value = ""; autogrow();
    setBusy(true);
    chatUI.thinking(true);
    // send_message は即 {cid} を返す。実処理はPython側スレッドで走り、
    // 完了時に window.chatUI.done() が呼ばれてロック解除される（生成中はロック維持）。
    var p = (window.pywebview && window.pywebview.api)
      ? window.pywebview.api.send_message(text)
      : Promise.reject("bridge未接続");
    Promise.resolve(p).then(function (r) {
      try { r = typeof r === "string" ? JSON.parse(r) : r; } catch (e) {}
      if (r && r.cid) chatUI._activeCid = r.cid;
      chatUI.refreshConvs();   // 新規会話をサイドバーに反映
    }).catch(function (e) { chatUI.addError(String(e)); setBusy(false); });
  }
  // Pythonが処理完了時に呼ぶ（生成など長い処理の後の入力解放）
  chatUI.done = function () { setBusy(false); chatUI.thinking(false); chatUI.refreshConvs(); chatUI.refreshAccount(); };

  function autogrow() {
    el.field.style.height = "auto";
    el.field.style.height = Math.min(el.field.scrollHeight, 180) + "px";
  }

  el.send.addEventListener("click", doSend);
  el.field.addEventListener("input", autogrow);
  el.field.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); doSend(); }
  });

  // Python→UI はポーリングで受け取る（WebView2のUIスレッド制約回避）
  function startPolling() {
    setInterval(function () {
      if (!(window.pywebview && window.pywebview.api && window.pywebview.api.poll)) return;
      window.pywebview.api.poll().then(function (updates) {
        if (!updates || !updates.length) return;
        updates.forEach(function (u) {
          var fn = chatUI[u.fn];
          if (typeof fn === "function") { try { fn.apply(chatUI, u.args || []); } catch (e) {} }
        });
      }).catch(function () {});
    }, 120);
  }

  // ---- i18n（表示言語の切り替え） ----
  // data-i18n(本文) / data-i18n-ph(placeholder) / data-i18n-title(title+aria) /
  // data-i18n-prompt(チップ送信文) を持つ全要素の「日本語原文」を集める。
  // DOM属性に無い動的メッセージ用のキーも翻訳マップに載せる
  var EXTRA_I18N_KEYS = ["接続できました", "接続できませんでした", "保存しました", "設定を開く"];
  function collectI18nKeys() {
    var seen = {};
    ["data-i18n", "data-i18n-ph", "data-i18n-title", "data-i18n-prompt"].forEach(function (attr) {
      var nodes = document.querySelectorAll("[" + attr + "]");
      for (var i = 0; i < nodes.length; i++) seen[nodes[i].getAttribute(attr)] = 1;
    });
    EXTRA_I18N_KEYS.forEach(function (k) { seen[k] = 1; });
    return Object.keys(seen);
  }
  // Pythonの i18n.T() で翻訳したマップを受け取り、DOMを差し替える。
  function applyStrings(map) {
    window.__i18n = map || {};   // 動的メッセージ用（chatUI.t で参照）
    function each(attr, apply) {
      var nodes = document.querySelectorAll("[" + attr + "]");
      for (var i = 0; i < nodes.length; i++) {
        var k = nodes[i].getAttribute(attr);
        var v = (map && map[k] != null) ? map[k] : k; // 未収録は原文
        apply(nodes[i], v);
      }
    }
    each("data-i18n", function (n, v) { n.textContent = v; });
    each("data-i18n-ph", function (n, v) { n.placeholder = v; });
    each("data-i18n-title", function (n, v) { n.title = v; n.setAttribute("aria-label", v); });
    each("data-i18n-prompt", function (n, v) { n.dataset.prompt = v; });
  }
  // 言語を適用（Pythonにキー一覧を渡して翻訳を取得）
  function applyLang(lang) {
    if (!(window.pywebview && window.pywebview.api && window.pywebview.api.get_strings)) {
      applyStrings(null); // bridge未接続時は原文（＝日本語）で初期化
      return;
    }
    window.pywebview.api.get_strings(lang || "", collectI18nKeys()).then(function (res) {
      try { res = typeof res === "string" ? JSON.parse(res) : res; } catch (e) {}
      if (res && res.lang) document.documentElement.lang = res.lang;
      applyStrings(res && res.map);
    }).catch(function () { applyStrings(null); });
  }
  chatUI.applyLang = applyLang; // 設定画面など他所からの言語切替用に公開

  // 起動時にPythonから初期情報（プラン・言語）を取得 ＋ i18n適用 ＋ ポーリング開始
  window.addEventListener("pywebviewready", function () {
    startPolling();
    chatUI.refreshConvs();   // サイドバーに保存済み会話を復元表示
    chatUI.refreshAccount(); // アカウント（プラン＋クレジットリング）
    chatUI.refreshAccountLogin(); // TomatoAI ログイン状態
    var a = (window.pywebview && window.pywebview.api) || null;
    if (a && a.get_init) {
      a.get_init().then(function (info) {
        try { info = typeof info === "string" ? JSON.parse(info) : info; } catch (e) {}
        if (info && info.plan) chatUI.setPlan(info.plan);
        applyLang(info && info.lang);
      });
    } else {
      applyLang();
    }
    // 初回セットアップ判定（規約未同意ならオンボーディングを表示）
    if (a && a.get_account_state) {
      a.get_account_state().then(function (st) {
        try { st = typeof st === "string" ? JSON.parse(st) : st; } catch (e) {}
        st = st || {};
        if (st.plan === "pro") chatUI.setPlan("Pro");
        else if (st.credits != null) chatUI.setPlan(chatUI.t("デモモード"));
        if (!st.agreed_terms) {
          // applyLangが先に走るよう少し待ってから表示（翻訳済みで出す）
          setTimeout(function () { chatUI.startOnboard(st); }, 350);
        }
      }).catch(function () {});
    }
  });
})();
