#!/usr/bin/env python3
"""hub 用の Redmine 一覧（/na-redmine・hub の Claude 用）。

Redmine には自分で問い合わせず、開発ダッシュボードの /api/redmine（5分キャッシュ）を localhost から読む。
取得・キャッシュ・枠との対応づけはダッシュボード側の1か所にまとめる（2026-11-25 ユーザー指定「ダッシュボードと共有化」）。

対象: 自分担当の未完了（新規登録・進行中・フィードバック）＋ウォッチ中（終了・解決・却下以外）。
1件2行: 番号・ステータス・区分・件名・作業中の枠（状態・スキル）／待ち・ブロックの相手先・最終更新（自分/他）・最新コメントの冒頭

並び（2026-11-25 ユーザーと決定）: ① /na-order で手で固定した順 → ② 着手可（未完了の待ちがなく、最新コメントが自分でない）
  → ③ 相手の番（最新コメントが自分）→ ④ 待ち（未完了の相手あり）。②〜④の中は 優先度 → 作業中 → 最終更新の古い順。
  固定の順は hub だけで持つ（order.json。ダッシュボード・Redmine には書かない）

使い方: python3 hub_redmine.py [--refresh|refresh] [--json] [件数] [優先度…] [全部|all]
  優先度: 今すぐ・急いで・高め・通常・低め（英語 now・urgent・high・normal・low も可。並べると複数）。
  「高め以上」「high+」のように付けるとそれより上も含む
  固定の順の操作: python3 hub_redmine.py --order [引数…]（/na-order と同じ）
  優先度を指定しないときは、件がある優先度の上から2段だけ（今すぐ・急いで。今すぐが無ければ急いで・高め。2026-11-25 ユーザー指定）
  「全部」で全優先度
  例: hub_redmine.py 高め以上 / hub_redmine.py 今すぐ 急いで 10 / hub_redmine.py 全部
"""
import datetime
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request

sys.dont_write_bytecode = True

DASH_DIR = os.path.expanduser("~/.local/share/dev-dashboard")
DASH_BASE = "http://127.0.0.1:8765"
ORDER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "order.json")  # hub/order.json（git・workspace に入れない）
STATE = {"busy": "処理中", "waiting": "確認待ち", "idle": "入力待ち", "stopped": "停止"}
JST = datetime.timezone(datetime.timedelta(hours=9))
PRIORITIES = ["低め", "通常", "高め", "急いで", "今すぐ"]  # Redmine の優先度（低い順）
PRI_EN = {"now": "今すぐ", "urgent": "急いで", "high": "高め", "normal": "通常", "low": "低め"}
CLOSED_NAMES = ("終了", "解決", "却下")  # 固定の順から自動で外すステータス


def dash_get(path):
    with open(os.path.join(DASH_DIR, "config.json"), encoding="utf-8") as f:
        key = json.load(f).get("key", "")
    req = urllib.request.Request(DASH_BASE + path, headers={"Cookie": f"dd_key={key}"})
    with urllib.request.urlopen(req, timeout=80) as r:
        return json.load(r)


def fetch(refresh=False):
    return dash_get("/api/redmine" + ("?refresh=1" if refresh else ""))


def fetch_issue(n):
    """一覧に無いチケット1件（番号・件名・ステータス・closed）。無ければ error を持つ dict。"""
    try:
        return dash_get(f"/api/redmine/issue?ticket={n}")
    except urllib.error.HTTPError as e:
        return {"error": f"#{n} が見つかりません（{e.code}）"}


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


def pri_name(a):
    """優先度の語（日本語・英語）を Redmine の名前に。違えば None。"""
    return a if a in PRIORITIES else PRI_EN.get(a.lower())


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
        elif (a.endswith("以上") and pri_name(a[:-2])) or (a.endswith("+") and pri_name(a[:-1])):
            p = pri_name(a[:-2] if a.endswith("以上") else a[:-1])
            pris |= set(PRIORITIES[PRIORITIES.index(p):])
        elif pri_name(a):
            pris.add(pri_name(a))
        elif a != "--json":
            unknown.append(a)
    return limit, (pris or None), refresh, unknown


def default_pris(items):
    """件がある優先度のうち上から2段。"""
    present = [p for p in reversed(PRIORITIES) if any(i.get("priority") == p for i in items)]
    return set(present[:2]) or None


# ---- 固定の順（/na-order）----

def load_order():
    try:
        with open(ORDER_FILE, encoding="utf-8") as f:
            return [int(x) for x in json.load(f).get("order", [])]
    except (OSError, ValueError):
        return []


def save_order(order):
    tmp = ORDER_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"order": order, "updated": datetime.datetime.now(JST).isoformat(timespec="seconds")}, f, ensure_ascii=False)
    os.replace(tmp, ORDER_FILE)


def known_issues(d):
    """番号 → チケット（一覧・担当外の直近作業・今日の担当外を全部見る）。"""
    out = {}
    for i in (d.get("today_extra") or []) + (d.get("issues") or []):
        out[i["id"]] = i
    return out


def pinned_items(d):
    """固定の順のチケット。終了・解決・却下になったものは順から外して保存し直す。"""
    order, known, out, keep = load_order(), known_issues(d), [], []
    for n in order:
        i = known.get(n)
        if i is None:
            j = fetch_issue(n)
            if j.get("error"):
                out.append({"id": n, "subject": j["error"], "status": "?", "outside": True})
                keep.append(n)
                continue
            i = {**j, "outside": True}
        if i.get("closed") or i.get("status") in CLOSED_NAMES:
            continue
        out.append(i)
        keep.append(n)
    if keep != order:
        save_order(keep)
    return out


# ---- 並べ方 ----

def tier(i):
    """1=着手可・2=相手の番（最新コメントが自分）・3=待ち（未完了の相手あり）。"""
    if any(r.get("kind") == "wait" and not r.get("closed") for r in i.get("relations") or []):
        return 3
    if (i.get("last") or {}).get("note_me"):
        return 2
    return 1


def sort_key(i):
    pri = PRIORITIES.index(i["priority"]) if i.get("priority") in PRIORITIES else -1
    return (-pri, 0 if i.get("sessions") else 1, (i.get("last") or {}).get("on") or i.get("updated_on") or "")


TIER_TITLE = {0: "固定（/na-order の順）", 1: "着手可（待ちなし・最新コメントが自分以外）", 2: "相手の番（最新コメントが自分）", 3: "待ち（未完了の相手あり）"}


def compact_text(d, limit=None, pris=None):
    """pris: None=既定（上から2段）・{"*"}=全部・それ以外=指定の優先度。固定の順は優先度の絞り込みに関係なく出す。"""
    if d.get("error"):
        return f"⛔ {d['error']}"
    pinned = pinned_items(d)
    pin_ids = {i["id"] for i in pinned}
    items = [i for i in targets(d) if i["id"] not in pin_ids]
    auto = pris is None
    if auto:
        pris = default_pris(targets(d))
    elif "*" in pris:
        pris = None
    if pris:
        items = [i for i in items if i.get("priority") in pris]
    groups = [(0, pinned)] + [(t, sorted((i for i in items if tier(i) == t), key=sort_key)) for t in (1, 2, 3)]
    total = len(pinned) + len(items)
    t = datetime.datetime.fromtimestamp(d.get("fetched_at") or 0, JST).strftime("%H:%M")
    cnt = {}
    for i in targets(d):
        cnt[i.get("priority")] = cnt.get(i.get("priority"), 0) + 1
    by_pri = " ".join(f"{p}{cnt[p]}" for p in reversed(PRIORITIES) if cnt.get(p))
    filt = f"・{'既定の' if auto else ''}絞り込み: {'/'.join(p for p in reversed(PRIORITIES) if p in pris)}" if pris else ""
    lines = [f"担当 {d.get('mine_count', 0)}件＋ウォッチ {d.get('watch_count', 0)}件（{by_pri}{filt} → {total}件・Redmine {t} 時点）"]
    left = limit or total
    for tno, g in groups:
        if not g or left <= 0:
            continue
        lines.append(f"── {TIER_TITLE[tno]} {len(g)}件")
        for k, i in enumerate(g[:left], 1):
            pair = line_pair(i)
            if tno == 0:
                pair[0] = f"{k}. " + pair[0] + ("  [一覧外]" if i.get("outside") else "")
            lines += pair
        left -= len(g)
    if limit and limit < total:
        lines.append(f"…ほか {total - limit}件（件数を外すと全件）")
    if auto and pris:
        lines.append("（優先度を指定しないときは上から2段だけ。全優先度は /na-redmine all）")
    return "\n".join(lines)


def order_cmd(args):
    """/na-order: 引数なし=表示・番号を並べる=その順で置き換え・「番号 順位」=その位置に入れる・+番号=末尾に足す・-番号=外す・clear=全部外す。"""
    order = load_order()
    d = None
    if not args:
        pass
    elif args == ["clear"]:
        save_order([])
    else:
        toks = list(args)
        bad = [a for a in toks if not re.fullmatch(r"[+-]?\d{1,6}", a)]
        if bad:
            return f"⛔ 分からない引数: {' '.join(bad)}（番号を並べる・番号 順位・+番号・-番号・clear）"
        plain = [a for a in toks if a.isdigit()]
        if len(toks) == 2 and all(a.isdigit() for a in toks) and len(toks[1]) <= 3:
            n, pos = int(toks[0]), int(toks[1])  # 「番号 順位」: その位置に入れる（1始まり）
            adds = [n]
            order = [x for x in order if x != n]
            order.insert(max(0, min(pos - 1, len(order))), n)
        elif plain and len(plain) == len(toks):
            if any(len(a) < 4 for a in plain):
                return "⛔ チケット番号は4〜6桁です（順位を指定するときは「番号 順位」の2つだけ）"
            adds = list(dict.fromkeys(int(a) for a in plain))
            order = adds
        else:
            adds = []
            for a in toks:
                if not a[0] in "+-" or len(a) < 5:
                    return "⛔ 置き換え（番号を並べる）と +番号・-番号は混ぜられません。+/- は4〜6桁の番号に付けます"
                n = int(a[1:])
                order = [x for x in order if x != n]
                if a[0] == "+":
                    order.append(n)
                    adds.append(n)
        d = fetch()
        known = known_issues(d)
        for n in adds:
            if n not in known:
                j = fetch_issue(n)
                if j.get("error"):
                    return f"⛔ {j['error']}。固定の順は変えていません"
        save_order(order)
    d = d or fetch()
    known = known_issues(d)
    order = load_order()
    if not order:
        return "固定の順: なし（/na-order 14926 14921 で、この順で /na-redmine の先頭に固定）"
    lines = [f"固定の順（{len(order)}件。/na-redmine の先頭にこの順で出る）"]
    for k, n in enumerate(order, 1):
        i = known.get(n) or fetch_issue(n)
        if i.get("error"):
            lines.append(f"{k}. #{n} {i['error']}")
        else:
            lines.append(f"{k}. #{n} 【{i.get('priority') or '-'}】{i.get('status', '')} {cut(i.get('subject', ''), 40)}{'' if n in known else '  [一覧外]'}")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if args[:1] == ["--order"]:
        print(order_cmd(args[1:]))
    else:
        print(run(args))


def run(args):
    """CLI と hook（/na-redmine）の共通の入口。"""
    limit, pris, refresh, unknown = parse_args(args)
    if unknown:
        return (f"⛔ 分からない引数: {' '.join(unknown)}（件数・優先度（{'・'.join(reversed(PRIORITIES))}／now・urgent・high・normal・low、"
                "「高め以上」「high+」など）・全部/all・再取得/refresh）")
    d = fetch(refresh)
    if "--json" in args:
        ts = targets(d)
        ps = default_pris(ts) if pris is None else (None if "*" in pris else pris)
        return json.dumps([i for i in ts if not ps or i.get("priority") in ps], ensure_ascii=False, indent=1)
    return compact_text(d, limit, pris)


if __name__ == "__main__":
    main()
