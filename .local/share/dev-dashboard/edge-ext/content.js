// 開発ダッシュボード（ポート 8765）のページだけで動く。
// ① ダッシュボードのページ（/）: ページから window.postMessage で受けた URL を background に渡す（タブを開かずに済む）。
//    ページは data-dd-ext を見て、拡張機能が入っているかを知る。
// ② 合図のページ（/tabgroup#{"url":...,"group":...}）: Chrome から microsoft-edge: で来たとき用。URL を background に渡す。
//    ページ側は data-dd-ext を見て、拡張機能が無いときだけ自分で URL を開く。失敗したときはエラーをこのタブに出す。
if (location.port === "8765") {
  document.documentElement.dataset.ddExt = "1";
  if (location.pathname === "/tabgroup") {
    chrome.runtime.onMessage.addListener((msg) => {
      if (msg && msg.type === "dd-error") {
        document.body.textContent = "タブグループに入れられませんでした: " + msg.message;
        document.title = "失敗: 開発ダッシュボード → Edge";
      }
    });
    try {
      const d = JSON.parse(decodeURIComponent(location.hash.slice(1)));
      chrome.runtime.sendMessage({ type: "dd-open", sig: true, url: d.url, group: d.group });
    } catch (e) {
      document.documentElement.dataset.ddExt = "error";
    }
  } else {
    window.addEventListener("message", (e) => {
      const d = e.data;
      if (e.source !== window || e.origin !== location.origin || !d || d.type !== "dd-open-req") return;
      chrome.runtime.sendMessage({ type: "dd-open", sig: false, url: d.url, group: d.group }, (res) => {
        const err = chrome.runtime.lastError ? chrome.runtime.lastError.message : res && res.error;
        if (err) window.postMessage({ type: "dd-open-failed", url: d.url, message: err }, location.origin);
      });
    });
  }
}
