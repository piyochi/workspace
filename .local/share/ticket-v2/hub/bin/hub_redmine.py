#!/usr/bin/env python3
"""hub 用の Redmine 一覧（/na-redmine・hub の Claude 用）。

Redmine には自分で問い合わせず、開発ダッシュボードの /api/redmine（5分キャッシュ）を localhost から読む。
取得・キャッシュ・枠との対応づけはダッシュボード側の1か所にまとめる（2026-11-25 ユーザー指定「ダッシュボードと共有化」）。

対象: 自分担当の未完了（新規登録・進行中・フィードバック）＋ウォッチ中（終了・解決・却下以外）。
1件2行: 番号・ステータス・区分・件名・作業中の枠（状態・スキル）／待ち・ブロックの相手先・最終更新（自分/他）・最新コメントの冒頭

使い方: python3 hub_redmine.py [--refresh] [--json] [件数] [優先度…]
  優先度: 今すぐ・急いで・高め・通常・低め（並べると複数）。「高め以上」のように「以上」を付けるとそれより上も含む
  優先度を指定しないときは、件がある優先度の上から2段だけ（今すぐ・急いで。今すぐが無ければ急いで・高め。2026-11-25 ユーザー指定）
  「全部」で全優先度
  例: hub_redmine.py 高め以上 / hub_redmine.py 今すぐ 急いで 10 / hub_redmine.py 全部
"""
import datetime
import json
import os
import sys
import unicodedata
import urllib.request

sys.dont_write_bytecode = True

DASH_DIR = os.path.expanduser("~/.local/share/dev-dashboard")
DASH_URL = "http://127.0.0.1:8765/api/redmine"
STATE = {"busy": "処理中", "waiting": "確認待ち", "idle": "入力待ち", "stopped": "停止"}
JST = datetime.timezone(datetime.timedelta(hours=9))
PRIORITIES = ["低め", "通常", "高め", "急いで", "今すぐ"]  # Redmine の優先度（低い順）


def fetch(refresh=False):
    with open(os.path.join(DASH_DIR, "config.json"), encoding="utf-8") as f:
        key = json.load(f).get("key", "")
    req = urllib.request.Request(DASH_URL + ("?refresh=1" if refresh else ""), headers={"Cookie": f"dd_key={key}"})
    with urllib.request.urlopen(req, timeout=80) as r:
        return json.load(r)


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WFA" else 1 for c in s)


def cut(s, w):
    """表示幅 w に収める（はみ出したら … を付ける）。"""
    if width(s) <= w:
        return s
    out = ""
    for c in s:
        if width(out + c) > w - 1:
            break
        out += c
    return out + "…"


def jst(ts):
    try:
        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(JST)
        return t.strftime("%m/%d %H:%M")
    except (ValueError, AttributeError):
        return ""


def targets(d):
    """担当分＋ウォッチ分（下の「担当外・完了済み（直近に作業）」は除く）。"""
    n = (d.get("mine_count") or 0) + (d.get("watch_count") or 0)
    return d.get("issues", [])[:n]


def line_pair(i):
    tag = "[ウォッチ]" if i.get("watch") else ""
    head = f"#{i['id']} 【{i.get('priority') or '?'}】{i.get('status', '')}{(' ' + tag) if tag else ''} {cut(i.get('subject', ''), 40)}"
    sess = []
    for s in i.get("sessions") or []:
        sk = s.get("skill", "")
        sess.append(f"[{s['slot']}]{STATE.get(s.get('state'), s.get('state', ''))}{(' ' + sk + ('済' if s.get('skill_done') else '')) if sk else ''}")
    if sess:
        head += "   " + " ".join(sess)
    parts = []
    waits = [r for r in i.get("relations") or [] if r.get("kind") == "wait" and not r.get("closed")]
    blocks = [r for r in i.get("relations") or [] if r.get("kind") == "blocking" and not r.get("closed")]
    if waits:
        parts.append("待ち: " + " ".join(f"#{r['id']}({r.get('status') or r.get('phrase') or '?'})" for r in waits))
    if blocks:
        parts.append("ブロック先: " + " ".join(f"#{r['id']}" for r in blocks))
    last = i.get("last") or {}
    if last.get("on"):
        who = "自分" if last.get("me") else "他"
        note = f"「{'自: ' if last.get('note_me') else ''}{cut(last['note'], 48)}」" if last.get("note") else ""  # 最新コメントが自分なら「自:」
        parts.append(f"更新: {who} {jst(last['on'])}{note}")
    return [head, "   " + "  ".join(parts) if parts else "   （待ち・更新の情報なし）"]


def parse_args(args):
    """引数を (件数, 優先度の集合 or None, 再取得, 分からない語) に分ける。"""
    limit, pris, refresh, unknown = None, set(), False, []
    for a in args:
        if a in ("全部", "all", "--all"):
            pris.add("*")
        elif a.isdigit():
            limit = int(a)
        elif a in ("再取得", "refresh", "--refresh", "-r"):
            refresh = True
        elif a.endswith("以上") and a[:-2] in PRIORITIES:
            pris |= set(PRIORITIES[PRIORITIES.index(a[:-2]):])
        elif a in PRIORITIES:
            pris.add(a)
        elif a != "--json":
            unknown.append(a)
    return limit, (pris or None), refresh, unknown


def default_pris(items):
    """件がある優先度のうち上から2段。"""
    present = [p for p in reversed(PRIORITIES) if any(i.get("priority") == p for i in items)]
    return set(present[:2]) or None


def compact_text(d, limit=None, pris=None):
    """pris: None=既定（上から2段）・{"*"}=全部・それ以外=指定の優先度。"""
    if d.get("error"):
        return f"⛔ {d['error']}"
    items = targets(d)
    auto = pris is None
    if auto:
        pris = default_pris(items)
    elif "*" in pris:
        pris = None
    if pris:
        items = [i for i in items if i.get("priority") in pris]
    shown = items[:limit] if limit else items
    t = datetime.datetime.fromtimestamp(d.get("fetched_at") or 0, JST).strftime("%H:%M")
    cnt = {}
    for i in targets(d):
        cnt[i.get("priority")] = cnt.get(i.get("priority"), 0) + 1
    by_pri = " ".join(f"{p}{cnt[p]}" for p in reversed(PRIORITIES) if cnt.get(p))
    filt = f"・{'既定の' if auto else ''}絞り込み: {'/'.join(p for p in reversed(PRIORITIES) if p in pris)} → {len(items)}件" if pris else ""
    lines = [f"担当 {d.get('mine_count', 0)}件＋ウォッチ {d.get('watch_count', 0)}件（{by_pri}{filt}・Redmine {t} 時点・枠で作業中→今日作業→優先度の順）"]
    for i in shown:
        lines += line_pair(i)
    if len(shown) < len(items):
        lines.append(f"…ほか {len(items) - len(shown)}件（件数を外すと全件）")
    if auto and pris:
        lines.append("（優先度を指定しないときは上から2段だけ。全優先度は /na-redmine 全部）")
    return "\n".join(lines)


def main():
    print(run(sys.argv[1:]))


def run(args):
    """CLI と hook（/na-redmine）の共通の入口。"""
    limit, pris, refresh, unknown = parse_args(args)
    if unknown:
        return f"⛔ 分からない引数: {' '.join(unknown)}（件数・優先度（{'・'.join(reversed(PRIORITIES))}、「高め以上」など）・全部・再取得）"
    d = fetch(refresh)
    if "--json" in args:
        ts = targets(d)
        ps = default_pris(ts) if pris is None else (None if "*" in pris else pris)
        return json.dumps([i for i in ts if not ps or i.get("priority") in ps], ensure_ascii=False, indent=1)
    return compact_text(d, limit, pris)


if __name__ == "__main__":
    main()
