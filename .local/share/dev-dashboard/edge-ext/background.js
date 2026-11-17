// 開発ダッシュボードから来た URL を、名前つきのタブグループ（既定「開発ダッシュボード」）で開く。
// - 同じ名前のグループがあればそこに足す（別のウィンドウにあればそのウィンドウで開く）
// - グループの中に同じ URL のタブが既にあれば、新しく開かずにそのタブを出す
// - ダッシュボードがアプリのウィンドウ（タブの無いウィンドウ）で開かれていても、グループは普通のウィンドウに作る
const DEFAULT_GROUP = "開発ダッシュボード";

// sig = true: 合図のページから（終わったら合図のタブを閉じる。失敗したらそのタブにエラーを出す）
// sig = false: ダッシュボードのページから直接（失敗したら返事でエラーを返し、ページが普通に開き直す）
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || msg.type !== "dd-open" || !sender.tab) return;
  openInGroup(msg, sender.tab).then(
    () => { if (msg.sig) chrome.tabs.remove(sender.tab.id).catch(() => {}); else reply({ ok: true }); },
    (e) => {
      const message = String((e && e.message) || e);
      if (msg.sig) chrome.tabs.sendMessage(sender.tab.id, { type: "dd-error", message }).catch(() => {});
      else reply({ error: message });
    },
  );
  return true;  // reply を後で呼ぶ
});

// グループを作れる普通のウィンドウ: 頼んできたタブのウィンドウ → 最後に使った普通のウィンドウ → 新しく作る
async function normalWindowId(sigTab) {
  const w = await chrome.windows.get(sigTab.windowId).catch(() => null);
  if (w && w.type === "normal") return w.id;
  const last = await chrome.windows.getLastFocused({ windowTypes: ["normal"] }).catch(() => null);
  if (last && last.type === "normal") return last.id;
  const all = await chrome.windows.getAll({ windowTypes: ["normal"] });
  if (all.length) return all[0].id;
  return (await chrome.windows.create({ focused: true })).id;
}

async function openInGroup({ url, group }, sigTab) {
  if (typeof url !== "string" || !/^https?:\/\//.test(url)) throw new Error("開く URL が不正です: " + url);
  const title = typeof group === "string" && group ? group.slice(0, 50) : DEFAULT_GROUP;
  const home = await normalWindowId(sigTab);
  const groups = await chrome.tabGroups.query({ title });
  const g = groups.find((x) => x.windowId === home) || groups[0];
  if (g) {
    const same = (await chrome.tabs.query({ groupId: g.id })).find((t) => t.url === url || t.pendingUrl === url);
    if (same) {
      if (g.collapsed) await chrome.tabGroups.update(g.id, { collapsed: false });
      await chrome.tabs.update(same.id, { active: true });
      await chrome.windows.update(same.windowId, { focused: true });
      return;
    }
  }
  const windowId = g ? g.windowId : home;
  const tab = await chrome.tabs.create({ url, windowId, active: true });
  if (g) {
    await chrome.tabs.group({ groupId: g.id, tabIds: tab.id });
    if (g.collapsed) await chrome.tabGroups.update(g.id, { collapsed: false });
  } else {
    const gid = await chrome.tabs.group({ tabIds: tab.id, createProperties: { windowId } });
    await chrome.tabGroups.update(gid, { title, color: "blue" });
  }
  await chrome.windows.update(windowId, { focused: true });
}
