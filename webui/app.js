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

  // ---- AI発話のアクションバー：👍 👎 再生成 共有 コピー ----
  var _ICON = {
    up:   '<path d="M7 22V11l5-9a2 2 0 0 1 2 2v5h5.5a2 2 0 0 1 2 2.4l-1.6 8A2 2 0 0 1 18 22H7z"/><path d="M7 11H4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3"/>',
    down: '<path d="M17 2v11l-5 9a2 2 0 0 1-2-2v-5H4.5a2 2 0 0 1-2-2.4l1.6-8A2 2 0 0 1 6 2h11z"/><path d="M17 13h3a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1h-3"/>',
    redo: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
    share:'<path d="M12 16V3"/><path d="M8 7l4-4 4 4"/><path d="M4 14v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  };
  function _act(name, title, icon) {
    return '<button class="actbtn" data-act="' + name + '" title="' + title + '" aria-label="' + title + '"' +
      ' data-i18n-title="' + title + '"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + icon + "</svg></button>";
  }
  var ACTS_HTML = '<div class="acts">' +
    _act("up", "良い回答", _ICON.up) + _act("down", "良くない回答", _ICON.down) +
    _act("redo", "再生成", _ICON.redo) + _act("share", "共有", _ICON.share) +
    _act("copy", "コピー", _ICON.copy) + "</div>";

  // ボタンを一瞬チェックにして「効いた」ことを伝える
  function _flash(btn) {
    var old = btn.innerHTML;
    btn.classList.add("ok");
    btn.innerHTML = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';
    setTimeout(function () { btn.classList.remove("ok"); btn.innerHTML = old; }, 1200);
  }
  function _msgText(msg) {
    var t = msg.querySelector(".ai-body .txt");
    return t ? (t.innerText || t.textContent || "").trim() : "";
  }
  function wireActs(msg) {
    var bar = msg.querySelector(".acts");
    if (!bar || bar._wired) return;
    bar._wired = true;
    bar.addEventListener("click", function (e) {
      var btn = e.target.closest && e.target.closest(".actbtn");
      if (!btn) return;
      var act = btn.getAttribute("data-act");
      if (act === "copy") {
        _copy(_msgText(msg)); _flash(btn);
      } else if (act === "share") {
        var text = _msgText(msg);
        if (navigator.share) { navigator.share({ text: text }).catch(function () {}); }
        else { _copy(text); _flash(btn); }   // 共有APIが無い環境（デスクトップ）はコピーで代替
      } else if (act === "redo") {
        _regenerate(msg);
      } else if (act === "up" || act === "down") {
        // 👍/👎 は排他。もう一度押すと取り消し
        var other = bar.querySelector('[data-act="' + (act === "up" ? "down" : "up") + '"]');
        if (other) other.classList.remove("active");
        btn.classList.toggle("active");
        _feedback(act, _msgText(msg), btn.classList.contains("active"));
      }
    });
  }
  function _copy(text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    } catch (e) {}
    var ta = document.createElement("textarea");   // 古い/非セキュアな環境向けフォールバック
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
  }
  function _feedback(kind, text, on) {
    var a = api();
    if (a && a.rate_message) { try { a.rate_message(kind, text, !!on); } catch (e) {} }
  }
  // 直前の自分の発話をもう一度送る＝作り直し（発話バブルは増やさない）
  function _regenerate(msg) {
    var prev = msg, userText = null;
    while ((prev = prev.previousElementSibling)) {
      if (prev.classList.contains("user")) {
        var b = prev.querySelector(".bubble");
        userText = b ? (b.innerText || b.textContent || "").trim() : null;
        break;
      }
    }
    if (!userText) return;
    msg.remove();                        // 古い回答を消してから作り直す
    chatUI.sendText(userText, true);     // true = ユーザー吹き出しは出さない
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
      d.innerHTML = AI_AVATAR + '<div class="ai-body"><div class="txt md">' + mdToHtml(text) +
        "</div>" + ACTS_HTML + "</div>";
      el.thread.appendChild(d);
      wireActs(d);
      scrollBottom();
    },

    thinking: function (on) {
      var ex = document.getElementById("thinking");
      if (on) {
        if (ex) return;
        ensureThread();
        var d = document.createElement("div");
        d.id = "thinking"; d.className = "msg ai";
        d.innerHTML = AI_AVATAR + '<div class="ai-body"><div class="txt thinking-txt">' +
          '<span class="think-word">THINKING</span><span class="think-dots"><i>.</i><i>.</i><i>.</i></span></div></div>';
        el.thread.appendChild(d); scrollBottom();
      } else if (ex) { ex.remove(); }
    },

    // 生成中：見出し＋スケルトン。動画が入る場所を先に確保して光らせる。
    startProgress: function (id, title) {
      ensureThread();
      chatUI.thinking(false);
      var d = document.createElement("div");
      d.className = "msg ai";
      d.innerHTML = AI_AVATAR +
        '<div class="ai-body"><div class="gen" id="' + id + '">' +
        '<div class="gen-hd"><span class="gen-spark"><i></i><i></i><i></i></span>' +
        '<span class="ttl">' + esc(title || chatUI.t("動画を作成しています")) + "</span></div>" +
        '<div class="gen-step">' + esc(chatUI.t("準備しています…")) + "</div>" +
        '<div class="gen-canvas">' +
        '<button class="gen-preview" type="button">' + esc(chatUI.t("プレビューを見る")) + "</button>" +
        "</div></div></div>";
      el.thread.appendChild(d);
      var btn = d.querySelector(".gen-preview");
      if (btn) btn.addEventListener("click", function (e) {
        e.stopPropagation();
        chatUI.openPreview(id);
      });
      scrollBottom();
    },
    updateProgress: function (id, stepText) {
      var c = document.getElementById(id);
      if (!c) return;
      var s = c.querySelector(".gen-step");
      if (s) s.textContent = stepText;
      scrollBottom();
    },
    finishProgress: function (id, title) {
      var c = document.getElementById(id);
      if (!c) return;
      c.classList.add("done");
      var hd = c.querySelector(".gen-hd");
      if (hd) hd.innerHTML = '<span class="check">✓</span><span class="ttl">' +
        esc(title || chatUI.t("完了")) + "</span>";
      var st = c.querySelector(".gen-step");
      if (st) st.remove();
    },
    // 「プレビューを見る」→ 右からエディタをスライドイン
    openPreview: function (id, src, title) {
      chatUI.openEditor(src, title);
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
        '<button class="btn" data-edit="1">編集する</button>' +
        '<button class="btn" onclick="chatUI.openFile(\'' + esc(v.path) + '\')">フォルダで開く</button>' +
        "</div></div></div></div>";
      var eb = d.querySelector("[data-edit]");
      if (eb) eb.addEventListener("click", function () {
        chatUI.openEditor(src, v.title || chatUI.t("完成した動画"), v.id || "");
      });
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
  // スマホ/iPad縦ではサイドバーが本文に重なるので、既定は閉じておく
  function isNarrow() {
    return window.matchMedia && window.matchMedia("(max-width:860px)").matches;
  }
  (function restoreSidebar() {
    var app = document.querySelector(".app");
    if (!app) return;
    var collapsed = false;
    try { collapsed = localStorage.getItem("tc_sidebar_collapsed") === "1"; } catch (e) {}
    if (isNarrow()) collapsed = true;   // 狭い画面は必ず閉じた状態で開始
    if (collapsed) app.classList.add("sidebar-collapsed");
  })();
  // 背景タップでサイドバーを閉じる（スマホのドロワー）
  (function bindBackdrop() {
    var bd = document.getElementById("sidebarBackdrop");
    if (bd) bd.addEventListener("click", function () { chatUI.setSidebar(true); });
  })();
  // 狭い画面でサイドバー内の項目を選んだら自動で閉じる
  (function autoCloseOnNav() {
    var sb = document.querySelector(".sidebar");
    if (!sb) return;
    sb.addEventListener("click", function (e) {
      if (!isNarrow()) return;
      if (e.target && e.target.closest && e.target.closest("button,a")) {
        chatUI.setSidebar(true);
      }
    });
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
  // ================= スケジュール（月カレンダー・DnD） =================
  // 予約は「時刻 ＋ プロンプト」。日をクリックして、話しかけるように書くだけ。
  var WDAY = ["月", "火", "水", "木", "金", "土", "日"];
  var _schedMonth = null;   // 表示中の月の1日
  var _schedTasks = [];

  function firstOf(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function localISO(dt) {   // タイムゾーンずれを避けてローカルISO（秒まで）
    return dt.getFullYear() + "-" + pad2(dt.getMonth() + 1) + "-" + pad2(dt.getDate()) +
      "T" + pad2(dt.getHours()) + ":" + pad2(dt.getMinutes()) + ":00";
  }
  function dayKey(d) { return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()); }

  chatUI.closeSchedule = function () {
    var p = document.getElementById("schedulePanel"); if (p) p.style.display = "none";
  };
  chatUI.openSchedule = function () {
    chatUI.closeSearch && chatUI.closeSearch();
    chatUI.closeStats && chatUI.closeStats();
    chatUI.closeCloud && chatUI.closeCloud();
    var p = document.getElementById("schedulePanel"); if (p) p.style.display = "flex";
    if (!_schedMonth) _schedMonth = firstOf(new Date());
    wirePalette();
    loadSchedule();
  };
  // ‹ / › / 今月
  chatUI.schedMonth = function (dir) {
    if (!_schedMonth) _schedMonth = firstOf(new Date());
    if (dir === 0) _schedMonth = firstOf(new Date());
    else _schedMonth = new Date(_schedMonth.getFullYear(), _schedMonth.getMonth() + dir, 1);
    renderMonth();
  };

  function loadSchedule() {
    var a = api();
    if (!a || !a.list_schedule) { _schedTasks = []; renderMonth(); return; }
    a.list_schedule().then(function (list) {
      try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (e) {}
      _schedTasks = list || [];
      renderMonth();
    }).catch(function () { _schedTasks = []; renderMonth(); });
  }

  function renderMonth() {
    var grid = document.getElementById("schedGrid");
    if (!grid || !_schedMonth) return;
    var first = _schedMonth;
    var lbl = document.getElementById("schedWeekLabel");
    if (lbl) lbl.textContent = first.getFullYear() + "年 " + (first.getMonth() + 1) + "月";

    // グリッドの開始＝その月の1日を含む週の月曜
    var lead = (first.getDay() + 6) % 7;             // 月=0
    var gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - lead);
    var now = new Date();
    var todayK = dayKey(now);

    // 予約を日付ごとに束ねる（時刻順）
    var byDay = {};
    _schedTasks.forEach(function (t) {
      var dt = new Date(t.run_at);
      if (isNaN(dt)) return;
      (byDay[dayKey(dt)] = byDay[dayKey(dt)] || []).push(t);
    });
    Object.keys(byDay).forEach(function (k) {
      byDay[k].sort(function (a, b) { return new Date(a.run_at) - new Date(b.run_at); });
    });

    var head = "<thead><tr>";
    for (var w = 0; w < 7; w++) head += '<th class="' + (w >= 5 ? "we" : "") + '">' + WDAY[w] + "</th>";
    head += "</tr></thead>";

    // 6週まで（その月が収まったら止める）
    var body = "<tbody>", cur = new Date(gridStart);
    for (var r = 0; r < 6; r++) {
      body += "<tr>";
      for (var c = 0; c < 7; c++) {
        var k = dayKey(cur);
        var out = cur.getMonth() !== first.getMonth();
        var isToday = k === todayK;
        var isPast = new Date(cur.getFullYear(), cur.getMonth(), cur.getDate() + 1) <= now;
        var items = (byDay[k] || []).map(function (t) {
          var dt = new Date(t.run_at);
          var hhmm = pad2(dt.getHours()) + ":" + pad2(dt.getMinutes());
          return '<div class="scard' + (t.repeat ? " rep" : "") + '" draggable="true" data-tid="' + t.id + '"' +
            ' title="' + esc(hhmm + "  " + (t.prompt || "")) + '">' +
            '<span class="sc-time">' + hhmm + (t.repeat ? " 🔁" : "") + "</span>" +
            '<span class="sc-p">' + esc(t.prompt || "") + "</span>" +
            '<span class="x" data-cancel="' + t.id + '">✕</span></div>';
        }).join("");
        body += '<td class="daycell' + (out ? " out" : "") + (isToday ? " today" : "") +
          (isPast ? " past" : "") + '" data-day="' + k + '">' +
          '<div class="day-num">' + cur.getDate() + "</div>" +
          '<div class="day-items">' + items + "</div></td>";
        cur = new Date(cur.getFullYear(), cur.getMonth(), cur.getDate() + 1);
      }
      body += "</tr>";
      if (cur.getMonth() !== first.getMonth() && cur > first) break;
    }
    body += "</tbody>";
    grid.innerHTML = head + body;
    wireGridDnD();
  }

  var _dragPrompt = null, _dragTaskId = null;
  function wirePalette() {
    var chips = document.querySelectorAll("#schedulePanel .pchip");
    for (var i = 0; i < chips.length; i++) {
      var ch = chips[i];
      if (ch._wired) continue;
      ch._wired = true;
      ch.addEventListener("dragstart", function (e) {
        _dragPrompt = this.getAttribute("data-prompt") || "";
        _dragTaskId = null;
        try { e.dataTransfer.setData("text/plain", "chip"); e.dataTransfer.effectAllowed = "copy"; } catch (x) {}
      });
    }
  }

  // 既定の時刻：今日なら次の正時、先の日付なら10:00
  function defaultTimeFor(key) {
    var d = new Date();
    if (key !== dayKey(d)) return "10:00";
    var h = d.getHours() + 1;
    return h > 23 ? "23:30" : pad2(h) + ":00";
  }

  // ── 革命の中心：日をクリックして「時刻＋プロンプト」を書く ──
  function openDayEditor(td, opts) {
    opts = opts || {};
    var host = td.querySelector(".day-items") || td;
    if (host.querySelector(".sc-edit")) return;
    var key = td.getAttribute("data-day");
    var box = document.createElement("div");
    box.className = "sc-edit";
    box.innerHTML = '<input type="time" class="sc-time-in" value="' +
      (opts.time || defaultTimeFor(key)) + '">' +
      '<textarea rows="2" placeholder="' + esc(chatUI.t("話しかけるように書く…")) + '"></textarea>';
    host.appendChild(box);
    var ta = box.querySelector("textarea"), ti = box.querySelector(".sc-time-in");
    ta.value = opts.value || "";
    ta.focus();

    var closed = false;
    function close() { if (!closed) { closed = true; box.remove(); } }
    function save() {
      var text = ta.value.trim();
      if (!text) { close(); return; }
      var a = api(); if (!a) { close(); return; }
      var hm = (ti.value || "10:00").split(":");
      var parts = key.split("-");
      var dt = new Date(+parts[0], +parts[1] - 1, +parts[2], +hm[0] || 0, +hm[1] || 0, 0);
      var after = function (list) {
        try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (er) {}
        if (list && !list.error) { _schedTasks = list; renderMonth(); }
      };
      if (opts.taskId != null) {
        // 文章と時刻の両方を反映（時刻が変わっていれば移動も）
        var done = function () {
          if (a.update_schedule_prompt) a.update_schedule_prompt(opts.taskId, text).then(after);
        };
        if (opts.iso !== localISO(dt) && a.reschedule) a.reschedule(opts.taskId, localISO(dt)).then(done);
        else done();
      } else if (a.add_schedule) {
        a.add_schedule(localISO(dt), text, null).then(after);
      }
      close();
    }
    ta.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); save(); }   // Shift+Enter で改行
      else if (e.key === "Escape") { e.preventDefault(); close(); }
    });
    ta.addEventListener("blur", function () {
      // 時刻入力へフォーカスが移っただけなら閉じない
      setTimeout(function () { if (!box.contains(document.activeElement)) save(); }, 0);
    });
    box.addEventListener("click", function (e) { e.stopPropagation(); });
  }

  function wireGridDnD() {
    var grid = document.getElementById("schedGrid");
    if (!grid) return;
    grid.querySelectorAll(".scard").forEach(function (card) {
      card.addEventListener("dragstart", function (e) {
        _dragTaskId = parseInt(this.getAttribute("data-tid"), 10);
        _dragPrompt = null;
        try { e.dataTransfer.setData("text/plain", "card"); e.dataTransfer.effectAllowed = "move"; } catch (x) {}
        e.stopPropagation();
      });
      // カードをクリック → 時刻と文章を書き直す
      card.addEventListener("click", function (e) {
        if (e.target.hasAttribute("data-cancel")) return;   // ✕ は削除
        e.stopPropagation();
        var tid = parseInt(this.getAttribute("data-tid"), 10), t = null;
        for (var i = 0; i < _schedTasks.length; i++) if (_schedTasks[i].id === tid) t = _schedTasks[i];
        if (!t) return;
        var dt = new Date(t.run_at);
        openDayEditor(this.closest("td"), {
          value: t.prompt, taskId: tid, iso: t.run_at,
          time: pad2(dt.getHours()) + ":" + pad2(dt.getMinutes())
        });
      });
    });
    grid.querySelectorAll("[data-cancel]").forEach(function (x) {
      x.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = parseInt(this.getAttribute("data-cancel"), 10);
        var a = api(); if (a && a.cancel_schedule) a.cancel_schedule(id).then(function (list) {
          try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (er) {}
          _schedTasks = list || []; renderMonth();
        });
      });
    });
    grid.querySelectorAll("td.daycell").forEach(function (td) {
      td.addEventListener("dragover", function (e) {
        if (td.classList.contains("past")) return;
        e.preventDefault(); td.classList.add("dragover");
      });
      td.addEventListener("dragleave", function () { td.classList.remove("dragover"); });
      td.addEventListener("drop", function (e) {
        e.preventDefault(); td.classList.remove("dragover");
        if (td.classList.contains("past")) return;
        var key = td.getAttribute("data-day"), parts = key.split("-");
        var a = api(); if (!a) return;
        var after = function (list) {
          try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (er) {}
          if (list && !list.error) { _schedTasks = list; renderMonth(); }
        };
        if (_dragTaskId != null && a.reschedule) {
          // 別の日へ移動：時刻は保ったまま日付だけ差し替える
          var t = null;
          for (var i = 0; i < _schedTasks.length; i++) if (_schedTasks[i].id === _dragTaskId) t = _schedTasks[i];
          var old = t ? new Date(t.run_at) : new Date();
          var dt = new Date(+parts[0], +parts[1] - 1, +parts[2], old.getHours(), old.getMinutes(), 0);
          a.reschedule(_dragTaskId, localISO(dt)).then(after);
        } else if (_dragPrompt != null) {
          openDayEditor(td, { value: _dragPrompt });   // 文章を直せる状態で開く
        }
        _dragPrompt = null; _dragTaskId = null;
      });
      // 空きスペースをクリック → その日に予約を書く
      td.addEventListener("click", function (e) {
        if (td.classList.contains("past")) return;
        if (e.target.closest && e.target.closest(".scard")) return;
        openDayEditor(td);
      });
    });
  }


  // ================= 動画エディタ（右からスライドイン） =================
  // 開閉は transform だけを動かす（.app に editor-open を付けるとCSSがスライドさせる）。
  var _edSrc = null, _edPxPerSec = 120, _edRaf = null, _edFitPending = true;
  // 台本編集（#36/#37）：現在の素材の動画ID・ユーザーが消した行のカット区間・履歴
  var _edVid = null, _edCuts = [], _edHist = [[]], _edHistIdx = 0,
      _edScript = null, _edTab = "assets", _edActiveLine = -1, _edExporting = false;

  chatUI.openEditor = function (src, title, vid) {
    var app = document.querySelector(".app"), p = document.getElementById("editorPanel");
    if (!app || !p) return;
    var v = document.getElementById("edVideo");
    var t = document.getElementById("edTitle");
    if (title && t) t.textContent = title;
    if (src && src !== _edSrc) {
      _edSrc = src;
      _edVid = vid || null;
      _edFitPending = true;      // 新しい素材は全体が見える倍率で開く
      _edCuts = []; _edHist = [[]]; _edHistIdx = 0;   // カットと履歴は素材ごと
      _edScript = null; _edActiveLine = -1;
      if (v) { v.src = src; v.load(); }
      if (_edTab === "script") edLoadScript(true);
    } else if (vid && !_edVid) {
      _edVid = vid;
    }
    p.setAttribute("aria-hidden", "false");
    app.classList.add("editor-open");
    edBuildAssets();
    edUpdateButtons();
    // メタデータが来てから尺に合わせて目盛りとクリップを描く
    if (v && v.readyState >= 1) edRebuild();
  };
  chatUI.closeEditor = function () {
    var app = document.querySelector(".app"), p = document.getElementById("editorPanel");
    var v = document.getElementById("edVideo");
    if (v) { try { v.pause(); } catch (e) {} }
    if (app) app.classList.remove("editor-open");
    if (p) p.setAttribute("aria-hidden", "true");
    edStopTick();
  };

  function edFmt(sec) {
    sec = Math.max(0, sec || 0);
    var m = Math.floor(sec / 60), s = Math.floor(sec % 60), cs = Math.floor((sec % 1) * 100);
    return pad2(m) + ":" + pad2(s) + "." + pad2(cs);
  }
  function edFmtRuler(sec) {
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
    // 1時間未満の素材で "00:00:05" は読みづらいだけなので時は省く
    return (h ? h + ":" + pad2(m) : pad2(m)) + ":" + pad2(s);
  }
  // 素材全体がタイムラインの幅に収まる拡大率。開くたびに全体が見える。
  function edFitZoom() {
    var wrap = document.getElementById("edTrackWrap");
    var dur = edDispDur() || edDur();
    if (!wrap || !dur) return 120;
    var avail = Math.max(200, wrap.clientWidth - 42 - 20);
    return Math.min(400, Math.max(2, avail / dur));
  }
  function edDur() {
    var v = document.getElementById("edVideo");
    return (v && isFinite(v.duration) && v.duration > 0) ? v.duration : 0;
  }

  // ---- カット区間（#37）と表示時間の写像 ----
  // タイムラインは「カットを取り除いて詰めた姿」（リップル表示）で描く。
  // 動画要素は元ファイルのままなので、実時刻⇄表示時刻の変換を常に通す。
  function edCutRanges() {
    var dur = edDur();
    var rs = _edCuts
      .map(function (c) { return [Math.max(0, c.s), dur ? Math.min(dur, c.e) : c.e]; })
      .filter(function (r) { return r[1] > r[0]; })
      .sort(function (a, b) { return a[0] - b[0]; });
    var m = [];
    rs.forEach(function (r) {
      if (m.length && r[0] <= m[m.length - 1][1] + 0.01) {
        m[m.length - 1][1] = Math.max(m[m.length - 1][1], r[1]);
      } else m.push([r[0], r[1]]);
    });
    return m;
  }
  function edDispDur() {
    var dur = edDur(), cut = 0;
    edCutRanges().forEach(function (r) { cut += r[1] - r[0]; });
    return Math.max(0, dur - cut);
  }
  function edDispT(t) {          // 動画の実時刻 → タイムライン表示時刻
    var shift = 0, rs = edCutRanges();
    for (var i = 0; i < rs.length; i++) {
      if (t >= rs[i][1]) shift += rs[i][1] - rs[i][0];
      else if (t > rs[i][0]) return rs[i][0] - shift;   // カット中は入口に寄せる
    }
    return t - shift;
  }
  function edSrcT(d) {           // タイムライン表示時刻 → 動画の実時刻
    var rs = edCutRanges(), t = d;
    for (var i = 0; i < rs.length; i++) {
      if (t >= rs[i][0]) t += rs[i][1] - rs[i][0];
      else break;
    }
    return t;
  }

  // 目盛りの間隔は、拡大率に応じて「切りのいい秒数」を選ぶ
  function edTickStep() {
    var cands = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    for (var i = 0; i < cands.length; i++) if (cands[i] * _edPxPerSec >= 72) return cands[i];
    return 900;
  }
  function edRebuild() {
    var dur = edDur(), dispDur = edDispDur();
    var ruler = document.getElementById("edRuler");
    var laneV = document.getElementById("edLaneV"), laneA = document.getElementById("edLaneA");
    if (!ruler || !laneV || !laneA) return;
    if (_edFitPending && dur) {
      _edPxPerSec = edFitZoom();       // 素材全体が一目で見える倍率に合わせる
      _edFitPending = false;
      var z = document.getElementById("edZoom");
      if (z) z.value = Math.round(_edPxPerSec);
    }
    var w = Math.max(dispDur * _edPxPerSec, 10);

    var step = edTickStep(), html = "";
    for (var t = 0; t <= dispDur + 0.001; t += step) {
      html += '<span class="tick" style="left:' + (t * _edPxPerSec + 42) + 'px">' + edFmtRuler(t) + "</span>";
    }
    ruler.innerHTML = html;
    ruler.style.width = (w + 60) + "px";
    var tracks = document.getElementById("edTracks");
    if (tracks) tracks.style.width = (w + 60) + "px";

    // 台本で行を消すとクリップが分割される：カットを除いた「残す区間」を
    // 隙間を詰めて並べる（リップル表示）。カットが無ければ素材まるごと1クリップ。
    var rs = edCutRanges(), keeps = [], prev = 0;
    rs.forEach(function (r) {
      if (r[0] > prev + 0.01) keeps.push([prev, r[0]]);
      prev = r[1];
    });
    if (dur - prev > 0.01 || !keeps.length) keeps.push([prev, Math.max(dur, prev)]);
    var vh = "", ah = "", x = 0;
    keeps.forEach(function (k, i) {
      var cw = Math.max(2, (k[1] - k[0]) * _edPxPerSec - (i < keeps.length - 1 ? 2 : 0));
      var lblV = i === 0 ? '<span class="cliplbl">' + esc(chatUI.t("動画")) + "</span>" : "";
      var lblA = i === 0 ? '<span class="cliplbl">' + esc(chatUI.t("音声")) + "</span>" : "";
      vh += '<div class="ed-clip v" style="left:' + x + 'px;width:' + cw + 'px">' + lblV + "</div>";
      ah += '<div class="ed-clip a" style="left:' + x + 'px;width:' + cw + 'px">' + lblA + "</div>";
      x += (k[1] - k[0]) * _edPxPerSec;
    });
    laneV.innerHTML = vh;
    laneA.innerHTML = ah;
    edMovePlayhead();
  }
  function edMovePlayhead() {
    var v = document.getElementById("edVideo"), ph = document.getElementById("edPlayhead");
    var lab = document.getElementById("edTime");
    if (!v || !ph) return;
    var d = edDispT(v.currentTime || 0);
    ph.style.left = (42 + d * _edPxPerSec) + "px";
    if (lab) lab.textContent = edFmt(d);
  }
  function edTick() {
    // 再生中にカット区間へ入ったら飛ばす（＝消した行は再生されない）
    var v = document.getElementById("edVideo");
    if (v && !v.paused) {
      var rs = edCutRanges(), t = v.currentTime;
      for (var i = 0; i < rs.length; i++) {
        if (t >= rs[i][0] - 0.02 && t < rs[i][1]) {
          if (rs[i][1] >= edDur() - 0.05) { v.pause(); v.currentTime = rs[i][0]; }
          else v.currentTime = rs[i][1] + 0.01;
          break;
        }
      }
    }
    edMovePlayhead();
    edSyncActiveLine();
    _edRaf = requestAnimationFrame(edTick);
  }
  function edStartTick() { if (!_edRaf) _edRaf = requestAnimationFrame(edTick); }
  function edStopTick() { if (_edRaf) { cancelAnimationFrame(_edRaf); _edRaf = null; } }

  // 左レール：これまでに作った動画を素材として並べる
  function edBuildAssets() {
    var box = document.getElementById("edAssets");
    if (!box || box._filled) return;
    box._filled = true;
    var a = api();
    if (!a || !a.list_videos) { edRenderAssets([]); return; }
    a.list_videos().then(function (list) {
      try { list = typeof list === "string" ? JSON.parse(list) : list; } catch (e) {}
      edRenderAssets(list || []);
    }).catch(function () { edRenderAssets([]); });
  }
  function edRenderAssets(list) {
    var box = document.getElementById("edAssets");
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<div class="ed-empty">' + esc(chatUI.t("素材はまだありません")) + "</div>";
      return;
    }
    box.innerHTML = list.map(function (v) {
      var raw = String(v.path || "").replace(/\\/g, "/");
      var src = (/^(https?:)?\/\//.test(raw) || raw.charAt(0) === "/") ? raw : "file:///" + raw;
      return '<div class="ed-asset" data-src="' + esc(src) + '" data-title="' + esc(v.title || "") +
        '" data-vid="' + esc(v.id || "") + '">' +
        '<div class="thumb"><video src="' + esc(src) + '" preload="metadata" muted></video></div>' +
        '<div class="nm">' + esc(v.title || "動画") + "</div></div>";
    }).join("");
    box.querySelectorAll(".ed-asset").forEach(function (el2) {
      el2.addEventListener("click", function () {
        box.querySelectorAll(".ed-asset").forEach(function (x) { x.classList.remove("on"); });
        this.classList.add("on");
        chatUI.openEditor(this.getAttribute("data-src"), this.getAttribute("data-title"),
                          this.getAttribute("data-vid"));
      });
    });
    edApplySearch();
  }

  // ---- 左レールのタブ（素材 / ライブラリ / 台本） ----
  function edSetTab(name) {
    _edTab = name;
    document.querySelectorAll(".ed-tab").forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-tab") === name);
    });
    var panes = { assets: "edAssets", library: "edLibrary", script: "edScript" };
    Object.keys(panes).forEach(function (k) {
      var n = document.getElementById(panes[k]);
      if (n) n.style.display = (k === name) ? "" : "none";
    });
    if (name === "library") {
      var lb = document.getElementById("edLibrary");
      if (lb) lb.innerHTML = '<div class="ed-empty">' + esc(chatUI.t("ライブラリ機能は近日公開")) + "</div>";
    }
    if (name === "script") edLoadScript();
    edApplySearch();
  }

  // 検索欄：素材タブは名前、台本タブは本文で絞り込む
  function edApplySearch() {
    var inp = document.getElementById("edSearch");
    var q = ((inp && inp.value) || "").trim().toLowerCase();
    var sel = _edTab === "script" ? "#edScript .ed-line" :
              _edTab === "assets" ? "#edAssets .ed-asset" : null;
    if (!sel) return;
    document.querySelectorAll(sel).forEach(function (n) {
      n.style.display = (!q || (n.textContent || "").toLowerCase().indexOf(q) >= 0) ? "" : "none";
    });
  }

  // ---- 台本タブ（#36）：時刻つき字幕。行クリック=シーク、✕=カット(#37) ----
  function edLoadScript(force) {
    var box = document.getElementById("edScript");
    if (!box) return;
    if (_edScript && !force) { edRenderScript(); return; }
    if (!_edVid) {
      box.innerHTML = '<div class="ed-empty">' +
        esc(chatUI.t("この動画には台本がありません（YouTube由来の動画のみ）")) + "</div>";
      return;
    }
    box.innerHTML = '<div class="ed-empty">' + esc(chatUI.t("台本を取得しています…")) + "</div>";
    var a = api();
    if (!a || !a.get_transcript) return;
    var vid = _edVid;
    a.get_transcript(vid).then(function (d) {
      try { d = typeof d === "string" ? JSON.parse(d) : d; } catch (e) {}
      if (vid !== _edVid) return;              // 取得中に別の素材へ切り替えた
      if (!d || d.error || !(d.lines || []).length) {
        box.innerHTML = '<div class="ed-empty">' +
          esc((d && d.error) || chatUI.t("台本を取得できませんでした")) + "</div>";
        return;
      }
      _edScript = d.lines;
      edRenderScript();
    }).catch(function () {
      if (vid !== _edVid) return;
      box.innerHTML = '<div class="ed-empty">' + esc(chatUI.t("台本を取得できませんでした")) + "</div>";
    });
  }
  function edLineCut(i) {
    for (var k = 0; k < _edCuts.length; k++) if (_edCuts[k].li === i) return true;
    return false;
  }
  function edRenderScript() {
    var box = document.getElementById("edScript");
    if (!box || !_edScript) return;
    _edActiveLine = -1;
    box.innerHTML = _edScript.map(function (l, i) {
      var isCut = edLineCut(i);
      var cls = "ed-line" + (l.gone ? " gone" : "") + (isCut ? " cut" : "");
      return '<div class="' + cls + '" data-i="' + i + '">' +
        '<span class="tc">' + edFmtRuler(l.o) + "</span>" +
        '<span class="tx">' + esc(l.text) + "</span>" +
        (l.gone ? "" :
          '<button class="del" title="' + esc(chatUI.t(isCut ? "復元" : "この行をカット")) + '">' +
          (isCut ? "↩" : "✕") + "</button>") +
        "</div>";
    }).join("");
    box.querySelectorAll(".ed-line").forEach(function (row) {
      var i = +row.getAttribute("data-i");
      row.addEventListener("click", function (e) {
        if (e.target.closest && e.target.closest(".del")) return;
        edSeekLine(i);
      });
      var del = row.querySelector(".del");
      if (del) del.addEventListener("click", function (e) {
        e.stopPropagation();
        edToggleLineCut(i);
      });
    });
    edApplySearch();
  }
  function edSeekLine(i) {
    var l = _edScript && _edScript[i], v = document.getElementById("edVideo");
    if (!l || !v || !edDur()) return;
    var t = Math.min(Math.max(0, l.o), Math.max(0, edDur() - 0.05));
    var rs = edCutRanges();
    for (var k = 0; k < rs.length; k++) {
      if (t >= rs[k][0] && t < rs[k][1]) { t = Math.min(rs[k][1] + 0.01, edDur()); break; }
    }
    v.currentTime = t;
    edMovePlayhead();
    edSetActiveLine(i);
  }
  // 再生位置に合わせて台本の現在行をハイライト
  function edSyncActiveLine() {
    if (!_edScript || _edTab !== "script") return;
    var v = document.getElementById("edVideo");
    if (!v) return;
    var t = v.currentTime, idx = -1;
    for (var i = 0; i < _edScript.length; i++) {
      var l = _edScript[i];
      if (!l.gone && !edLineCut(i) && t >= l.o && t < Math.max(l.o2, l.o + 0.01)) { idx = i; break; }
    }
    if (idx !== _edActiveLine) edSetActiveLine(idx);
  }
  function edSetActiveLine(i) {
    _edActiveLine = i;
    var box = document.getElementById("edScript");
    if (!box) return;
    box.querySelectorAll(".ed-line.active").forEach(function (x) { x.classList.remove("active"); });
    if (i >= 0) {
      var row = box.querySelector('.ed-line[data-i="' + i + '"]');
      if (row) {
        row.classList.add("active");
        try { row.scrollIntoView({ block: "nearest" }); } catch (e) {}
      }
    }
  }

  // ---- 行の削除＝カット（#37）。履歴つき（元に戻す / やり直す） ----
  function edToggleLineCut(i) {
    var l = _edScript && _edScript[i];
    if (!l || l.gone) return;
    var idx = -1;
    for (var k = 0; k < _edCuts.length; k++) if (_edCuts[k].li === i) idx = k;
    if (idx >= 0) _edCuts.splice(idx, 1);
    else _edCuts.push({ s: l.o, e: Math.max(l.o2, l.o + 0.15), li: i });
    edPushHist();
    edAfterCutsChanged();
  }
  function edPushHist() {
    _edHist = _edHist.slice(0, _edHistIdx + 1);
    _edHist.push(JSON.parse(JSON.stringify(_edCuts)));
    _edHistIdx = _edHist.length - 1;
  }
  function edUndoRedo(dir) {
    var n = _edHistIdx + dir;
    if (n < 0 || n >= _edHist.length) return;
    _edHistIdx = n;
    _edCuts = JSON.parse(JSON.stringify(_edHist[n]));
    edAfterCutsChanged();
  }
  function edAfterCutsChanged() {
    edRenderScript();
    edRebuild();
    edUpdateButtons();
  }
  function edUpdateButtons() {
    var b = document.getElementById("edExport");
    if (b) {
      b.disabled = _edExporting || !_edCuts.length || !_edVid;
      b.textContent = _edExporting ? chatUI.t("書き出し中…") : chatUI.t("書き出す");
    }
    var u = document.getElementById("edUndo"), r = document.getElementById("edRedo");
    if (u) u.disabled = _edHistIdx <= 0;
    if (r) r.disabled = _edHistIdx >= _edHist.length - 1;
  }

  // ---- 書き出す：カットを適用して再レンダリング（Python側でffmpeg） ----
  function edExport() {
    if (_edExporting || !_edVid || !_edCuts.length) return;
    var a = api();
    if (!a || !a.export_cuts) return;
    _edExporting = true;
    edUpdateButtons();
    var cuts = edCutRanges().map(function (r) { return { s: r[0], e: r[1] }; });
    a.export_cuts(_edVid, cuts).then(function (d) {
      try { d = typeof d === "string" ? JSON.parse(d) : d; } catch (e) {}
      if (d && d.error) {
        _edExporting = false;
        edUpdateButtons();
        chatUI.addError(d.error);
      }
    }).catch(function () { _edExporting = false; edUpdateButtons(); });
  }
  // Python から書き出し完了通知（完成カードは addVideoCard で別途届く）
  chatUI.exportDone = function (ok) {
    _edExporting = false;
    edUpdateButtons();
    var box = document.getElementById("edAssets");
    if (box) box._filled = false;      // 次に開いたとき素材レールを更新
    if (ok) chatUI.closeEditor();
  };

  (function wireEditor() {
    var v = document.getElementById("edVideo");
    var scrim = document.getElementById("edScrim");
    if (scrim) scrim.addEventListener("click", chatUI.closeEditor);
    document.addEventListener("keydown", function (e) {
      var app = document.querySelector(".app");
      if (!app || !app.classList.contains("editor-open")) return;
      if (e.key === "Escape") chatUI.closeEditor();
      else if (e.key === " " && e.target === document.body) { e.preventDefault(); edTogglePlay(); }
    });
    if (v) {
      v.addEventListener("loadedmetadata", edRebuild);
      v.addEventListener("play", edStartTick);
      v.addEventListener("pause", function () { edStopTick(); edMovePlayhead(); });
      v.addEventListener("seeked", edMovePlayhead);
      v.addEventListener("ended", function () { edStopTick(); edMovePlayhead(); });
    }
    var play = document.getElementById("edPlay");
    if (play) play.addEventListener("click", edTogglePlay);

    // 拡大縮小
    var z = document.getElementById("edZoom");
    if (z) z.addEventListener("input", function () { _edPxPerSec = +this.value; edRebuild(); });
    var zi = document.getElementById("edZoomIn"), zo = document.getElementById("edZoomOut");
    if (zi) zi.addEventListener("click", function () { edZoomBy(1.4); });
    if (zo) zo.addEventListener("click", function () { edZoomBy(1 / 1.4); });

    // 目盛り／レーンをクリックしてシーク（表示時刻→カットを飛ばした実時刻へ変換）
    var wrap = document.getElementById("edTrackWrap");
    if (wrap) wrap.addEventListener("click", function (e) {
      var vv = document.getElementById("edVideo");
      if (!vv || !edDur()) return;
      if (e.target.closest && e.target.closest(".ed-track-hd")) return;
      var r = wrap.getBoundingClientRect();
      var x = e.clientX - r.left + wrap.scrollLeft - 42;
      vv.currentTime = Math.min(edDur(), Math.max(0, edSrcT(x / _edPxPerSec)));
      edMovePlayhead();
    });

    // 左レールのタブ切替（素材 / ライブラリ / 台本）
    document.querySelectorAll(".ed-tab").forEach(function (b) {
      b.addEventListener("click", function () { edSetTab(this.getAttribute("data-tab")); });
    });
    // 検索（現在のタブの中身を絞り込む）
    var sch = document.getElementById("edSearch");
    if (sch) sch.addEventListener("input", edApplySearch);
    // 元に戻す / やり直す / 書き出す
    var un = document.getElementById("edUndo"), re = document.getElementById("edRedo");
    if (un) un.addEventListener("click", function () { edUndoRedo(-1); });
    if (re) re.addEventListener("click", function () { edUndoRedo(1); });
    var ex = document.getElementById("edExport");
    if (ex) ex.addEventListener("click", edExport);
  })();

  function edTogglePlay() {
    var v = document.getElementById("edVideo");
    if (!v || !v.src) return;
    if (v.paused) v.play().catch(function () {}); else v.pause();
  }
  function edZoomBy(f) {
    _edPxPerSec = Math.min(400, Math.max(2, _edPxPerSec * f));
    var z = document.getElementById("edZoom");
    if (z) z.value = Math.round(_edPxPerSec);
    edRebuild();
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
    el.field.value = ""; autogrow();
    chatUI.sendText(text);
  }
  // 任意のテキストを送る共通経路（入力欄・再生成の両方から使う）。
  // skipUserBubble=true なら発話バブルを足さない（再生成用）。
  chatUI.sendText = function (text, skipUserBubble) {
    if (!text || busy) return;
    if (!skipUserBubble) chatUI.addUser(text);
    chatUI._firstTitleSet = true;
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
  };
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
  var EXTRA_I18N_KEYS = ["接続できました", "接続できませんでした", "保存しました", "設定を開く",
    "話しかけるように書く…", "動画を作成しています", "準備しています…", "プレビューを見る", "完了",
    "動画", "音声", "素材はまだありません",
    "台本を取得しています…", "台本を取得できませんでした",
    "この動画には台本がありません（YouTube由来の動画のみ）", "ライブラリ機能は近日公開",
    "この行をカット", "復元", "書き出し中…", "書き出す"];
  function collectI18nKeys() {
    var seen = {};
    ["data-i18n", "data-i18n-ph", "data-i18n-ph-narrow", "data-i18n-title", "data-i18n-prompt"].forEach(function (attr) {
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
    // 長いプレースホルダーはスマホだと2行に折り返して切れるので、短い方に差し替える
    each("data-i18n-ph-narrow", function (n, v) {
      n.dataset.phWide = n.placeholder;   // data-i18n-ph で入った通常版を退避
      n.dataset.phNarrow = v;
    });
    applyNarrowPlaceholder();
  }
  // 画面幅に応じて placeholder を出し分ける（回転・リサイズにも追従）。
  // i18n が走らなくても単体で動くよう、未設定なら属性から自分で取る。
  function applyNarrowPlaceholder() {
    var narrow = window.matchMedia && window.matchMedia("(max-width:860px)").matches;
    var nodes = document.querySelectorAll("[data-i18n-ph-narrow]");
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (!n.dataset.phWide) n.dataset.phWide = n.getAttribute("data-i18n-ph") || n.placeholder;
      if (!n.dataset.phNarrow) n.dataset.phNarrow = n.getAttribute("data-i18n-ph-narrow");
      var v = narrow ? n.dataset.phNarrow : n.dataset.phWide;
      if (v) n.placeholder = v;
    }
  }
  window.addEventListener("resize", applyNarrowPlaceholder);
  applyNarrowPlaceholder();
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
