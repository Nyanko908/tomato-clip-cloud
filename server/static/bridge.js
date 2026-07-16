/* bridge.js — Tomato Clip クラウドWeb版のブリッジシム。
 *
 * デスクトップ版は pywebview が window.pywebview.api.<method>(...) を Python に橋渡しするが、
 * ブラウザ版では代わりに fetch("/api/<method>") へ変換する。これにより既存の webui/app.js を
 * 【無改変】でそのまま動かせる（app.js は window.pywebview.api.X().then(...) を呼ぶだけ）。
 *
 * このスクリプトは index.html の <head> に注入され、app.js より前に window.pywebview を定義する。
 * pywebviewready イベントは app.js がリスナ登録した後（load時）に発火する。
 */
(function () {
  "use strict";

  function call(name, args) {
    return fetch("/api/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ args: args || [] }),
    }).then(function (res) {
      if (!res.ok) {
        return res.text().then(function (t) {
          throw new Error("HTTP " + res.status + ": " + t);
        });
      }
      // 返り値は素の JSON（dict / bool / list / null）。204等は null。
      return res.status === 204 ? null : res.json();
    });
  }

  // 任意のメソッド名を受け付ける Proxy。api.poll(), api.send_message(t), api.get_strings(l,k) 等。
  var api = new Proxy(
    {},
    {
      get: function (_t, name) {
        // Promise系ユーティリティへの誤アクセス（then等）を避ける
        if (typeof name !== "string") return undefined;
        return function () {
          var args = Array.prototype.slice.call(arguments);
          return call(name, args);
        };
      },
    }
  );

  window.pywebview = { api: api, platform: "cloud-web" };

  // pywebviewready を app.js のリスナ登録後に発火する。
  function fireReady() {
    try {
      window.dispatchEvent(new Event("pywebviewready"));
    } catch (e) {
      var ev = document.createEvent("Event");
      ev.initEvent("pywebviewready", true, true);
      window.dispatchEvent(ev);
    }
  }
  if (document.readyState === "complete") {
    setTimeout(fireReady, 0);
  } else {
    window.addEventListener("load", fireReady);
  }
})();
