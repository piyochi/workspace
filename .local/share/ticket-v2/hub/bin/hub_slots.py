#!/usr/bin/env python3
"""/na-slots-status の材料: monitor タブの全部の枠の今の状態を、Claude が表にまとめやすい形で出す（2026-11-26 ユーザー指定）。

/na-watch は固定したチケットの流れ、/na-list は画面の要約。ここは「いま誰が何を待っていて、どこで止まるか」を1枠1ブロックで出す。
材料: 開発ダッシュボードの /api/panes（枠・チケット・スキル）・/api/watch（流れ・状態・自動の依頼）、各枠の画面（hub_status）、
statusline の記録（最後に動いた時刻）、ct-fix-loop の state.json、hub の autopilot.json・docker.json。

  python3 -B hub_slots.py          … 全部の枠
  python3 -B hub_slots.py 5 9      … 指定した枠だけ（Codex の偶数枠は相方の Claude の枠と一緒に出る）
"""
import json
import os
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_docker as hd  # noqa: E402
import hub_redmine as hr  # noqa: E402
import hub_status as hs  # noqa: E402

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO = os.path.join(HUB, "autopilot.json")
CACHE = os.path.expanduser("~/.local/share/dev-dashboard/cache")
FIX_LOOP = os.path.expanduser("~/.claude/tmp/fix-loop")
STATE = {"busy": "処理中", "wait": "確認待ち（許可）", "idle": "入力待ち", "stopped": "未起動"}

# スキルごとの「次に止まる所」（hub の自動の依頼を含めて。README の流れと同じ）
NEXT_STOP = {
    "ct-redmine": "読み終わると、/na-next の対象なら hub が ct-analyze を頼む",
    "ct-analyze": "終わったら止まる（流れを選ぶ: 新規 /na-next 番号・不具合 /na-go 番号 fix）",
    "ct-architect": "終わったら止まる（結論を見て /na-next 番号 で ct-planner）",
    "ct-sweep": "終わると hub が ct-planner を頼む",
    "ct-scope": "終わると hub が ct-planner を頼む",
    "ct-planner": "終わったら止まる（計画を見て /na-next 番号 で ct-issue-docs）",
    "ct-issue-docs": "終わると hub が issue docs のコミットを頼み、止まる（実装は /na-go 番号）",
    "ct-ship-loop": "全フェーズの後 hub が ct-finish を頼み、push の確認で止まる",
    "ct-finish": "push の確認で止まる",
    "ct-fix-loop": "F5（施策の結果の確認）と push の確認で止まる",
    "ct-pr-turn": "指摘ごとの「対応する／しない」の選択と、投稿・push の前の確認で止まる",
    # 流れの外（各枠で直接進める作業）。最後に使ったスキルがこれなら、流れの段階より優先する（2026-11-26 [7] がリリース後なのに issue-docs と出た）
    "ct-pr-create": "PR を作り、Redmine でレビューを頼む前に確認で止まる",
    "ct-ci-fix": "CI が通るまで直す（push は起動時に決めた方針どおり）",
    "ct-deploy": "デプロイの後の確認まで（想定外が起きたら止まる）",
    "ct-browser-verify": "確認の結果を報告して止まる",
    "ct-pr-fix": "修正と返信の前に確認で止まる",
    "ct-pr-review": "投稿の前に確認で止まる",
}


def pr_live(url):
    """GitHub の今の PR の状態（ダッシュボードの取得分は少し古いので、枠のチケットの分だけ取り直す）"""
    try:
        r = subprocess.run(["gh", "pr", "view", url, "--json", "state,mergedAt,reviewDecision,baseRefName"],
                           capture_output=True, text=True, timeout=20)
        d = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    st = {"MERGED": "マージ済み", "OPEN": "オープン", "CLOSED": "閉じた"}.get(d.get("state"), d.get("state"))
    if d.get("mergedAt"):
        st += " " + time.strftime("%m/%d %H:%M", time.localtime(
            time.mktime(time.strptime(d["mergedAt"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone))
    if d.get("state") == "OPEN" and d.get("reviewDecision"):
        st += {"APPROVED": "・承認済み", "CHANGES_REQUESTED": "・修正依頼あり", "REVIEW_REQUIRED": "・レビュー待ち"}.get(d["reviewDecision"], "")
    return f"{st}（→ {d.get('baseRefName', '')}）"


def ago(ts):
    if not ts:
        return ""
    sec = max(0, int(time.time() - ts))
    return f"{sec // 60}分前" if sec < 3600 else f"{sec // 3600}時間{sec % 3600 // 60}分前"


def last_move(pane):
    """statusline が記録した会話のファイルの更新時刻（最後に動いた時刻）"""
    try:
        with open(os.path.join(CACHE, f"pane-{pane.lstrip('%')}.json")) as f:
            return os.path.getmtime(json.load(f)["transcript_path"])
    except (OSError, ValueError, KeyError):
        return None


def fix_state(n):
    try:
        with open(os.path.join(FIX_LOOP, str(n), "state.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main(argv):
    want = {int(a) - 1 if int(a) % 2 == 0 else int(a) for a in argv if a.isdigit()}  # Codex の枠は相方の Claude の枠で出す
    panes = hr.dash_get("/api/panes")
    watch = hr.dash_get("/api/watch")
    items = {i["id"]: i for i in watch.get("items", [])}
    auto = load(AUTO).get("tickets", {})
    docker = load(hd.STATE)
    holder = (docker.get("holder") or {}).get("ticket")
    queue = [q["ticket"] for q in hd.queue_sorted({"queue": list(docker.get("queue") or [])})]
    screens = {r["slot"]: r for r in hs.collect("monitor")}
    slots = {s["slot"]: s for s in panes.get("slots", [])}
    out = [f"取得 {time.strftime('%H:%M:%S')}・確認待ち {watch.get('attention', 0)} 件（/na-watch の固定分）"]
    out.append("開発用サーバー: " + (f"使用中 #{holder}" if holder else "使用中なし")
               + ("・待ち " + " → ".join(f"#{t}" for t in queue) if queue else ""))
    # 並びは /na-order の順（固定したチケットが先・上が先）。固定していないチケットの枠・空き枠はその後に枠番号の順（2026-11-26 ユーザー「優先順に」）
    order = [str(x) for x in load(hd.ORDER).get("order") or []]

    def rank(k):
        tk = [t for t in (slots[k].get("tickets") or [slots[k].get("ticket")]) if t]
        r = min((order.index(t) for t in tk if t in order), default=None)
        return (0, r, k) if r is not None else (1, 0, k)

    for n in sorted((k for k in slots if k % 2 == 1), key=rank):
        if want and n not in want:
            continue
        s, scr = slots[n], screens.get(n, {})
        cx, cxs = slots.get(n + 1, {}), screens.get(n + 1, {})
        tks = [t for t in (s.get("tickets") or [s.get("ticket")]) if t]
        out.append("")
        rk = rank(n)
        head = (f"優先 {rk[1] + 1}位 " if rk[0] == 0 else "優先 固定なし ") + f"[{n}] {s['env']} Claude: {STATE.get(s['state'], s['state'])}"
        if s["state"] != "stopped":
            head += f"（画面: {scr.get('state', '?')}"
            mv = last_move(s["pane"])
            head += f"・最後の動き {ago(mv)}）" if mv else "）"
            if s.get("fresh"):
                head += "・新しい会話（空き）"
            if s.get("subagents"):
                head += f"・サブエージェント {s['subagents']}"
            if s.get("ctx"):
                head += f"・会話 {s['ctx']['used'] // 1000}k"
        out.append(head)
        if s["state"] == "stopped":
            out.append("  （Claude が起動していない。/na-next で選ばれると起動して送る）")
        if tks:
            for t in tks:
                i = items.get(t, {})
                line = f"  チケット #{t}"
                if i:
                    line += f" {i.get('subject', '')[:40]}"
                out.append(line)
                if i:
                    out.append(f"    Redmine: {i.get('status', '')}・{i.get('priority', '')}"
                               + (f"・{i['ball']['label']}" if i.get("ball") else ""))
                    out.append(f"    流れの段階（決まった流れのスキルだけで判定。枠で直接進めた作業は入らない）: {i.get('stage') or '-'}・{i.get('state_label', '')}")
                    for pr in i.get("prs") or []:
                        live = pr_live(pr["url"]) if pr.get("url") else None
                        out.append(f"    PR {pr.get('repo', '')}#{pr.get('number')}: {live or pr.get('state', '') + '（ダッシュボードの取得分）'}")
                fx = fix_state(t)
                if fx:
                    w = {"codex": "Codex の返事待ち", "docker": "開発用サーバーの順番待ち", "user": "あなたの確認待ち"}.get(fx.get("waiting"), "")
                    out.append(f"    ct-fix-loop: {fx.get('step')} {fx.get('label', '')}・第{fx.get('round', 0)}回"
                               + (f"・{w}" if w else "") + (f"・止まっている（{fx['stop']}）" if fx.get("stop") else ""))
                if t == holder:
                    out.append("    開発用サーバー: 使用中")
                elif t in queue:
                    out.append(f"    開発用サーバー: 順番待ち {queue.index(t) + 1} 番目")
                a = auto.get(t, {})
                if a.get("pending"):
                    out.append(f"    hub: 起動待ちの依頼 {a['pending'].get('skill')}")
                lg = (a.get("log") or [])[-1:] if a else []
                for x in lg:
                    if time.time() - x.get("at", 0) < 12 * 3600:  # 半日より前の自動の依頼は出さない（古い記録が混ざるため）
                        out.append(f"    hub の最後の依頼: {time.strftime('%H:%M', time.localtime(x['at']))} {x.get('skill')}"
                                   + ("" if x.get("ok") else f" ⛔ {x.get('msg', '')[:80]}"))
        elif s["state"] != "stopped":
            out.append("  チケット: なし（空き）")
        sk = s.get("skill") or ""
        if sk:
            out.append(f"  最後に使ったスキル: {sk}（{'終了' if s.get('skill_done') else '実行中'}）")
        # 次に止まる所: 最後に使ったスキルが表にあればそれ（流れの外の作業も含む）。ct-handoff などの補助なら流れの段階で判断する
        flow_sk = sk if sk in NEXT_STOP else ""
        for t in tks:
            i = items.get(t, {})
            st = i.get("stage") or ""
            cand = "ct-pr-turn" if st.startswith("pr-turn") else "ct-fix-loop" if st.startswith("fix-loop") else (i.get("skill") or "")
            if not flow_sk and cand in NEXT_STOP:
                flow_sk = cand
        if flow_sk:
            stop = NEXT_STOP[flow_sk]
            fx = next((fix_state(t) for t in tks if fix_state(t)), None)
            if flow_sk == "ct-fix-loop" and fx and str(fx.get("step", "")).lstrip("F").isdigit() and int(str(fx["step"]).lstrip("F")) > 5:
                stop = "push の確認で止まる（F5 の確認は済み）"
            out.append(f"  次に止まる所（{flow_sk}）: {stop}")
        if scr.get("last"):
            out.append(f"  画面の最後の段落: {scr['last'][:220]}")
        if scr.get("pending"):
            out.append(f"  入力欄に未送信の文: {scr['pending'][:120]}")
        if cx:
            line = f"  相方 [{n + 1}] Codex: {STATE.get(cx['state'], cx['state'])}"
            if cx["state"] != "stopped" and cxs.get("last"):
                line += f"・画面: {cxs['last'][:120]}"
            out.append(line)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
