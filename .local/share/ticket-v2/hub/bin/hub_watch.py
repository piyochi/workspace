#!/usr/bin/env python3
"""hub の監視の表示（/na-watch・hub の Claude 用）。

判定は開発ダッシュボードの常駐ループ（server.py の watch_loop。20 秒ごと）が行い、/api/watch と
~/.local/share/ticket-v2/hub/watch.json に書く。ここはそれを読んで、1件を見出し＋ラベル付きの行（件名・流れ・実装・PR・自動）に整えるだけ。
対象は /na-order で固定したチケット（hub/order.json）。

見出し: 順・#番号【優先度】ステータス [枠] 状態 · スキル。流れは3段ずつ折り返す
流れ（新規開発 redmine→analyze→architect→(sweep)→(scope)→planner→issue-docs→ship-loop→finish、
不具合・負荷 redmine→analyze→fix-loop→finish）の印・施策の進み具合・フェーズ・PR・レビュー
  印: ✓ 済み / ▶ 実行中・途中 / ? 質問中 / ✗ 記録なし（後の段階が先に動いた） / ・ 未実行（() は省略可の段階）

使い方: python3 hub_watch.py [--refresh|refresh] [--json]
      python3 hub_watch.py --next 番号|枠 [枠] [sweep] [scope] [fix|new] [model=…] [effort=…] [dry] [補足の指示…]   … /na-next（止まっている所から次のスキルを頼み、以後は自動で頼む）
      python3 hub_watch.py --go 番号|枠 [枠] [fix|new] [--branch 名前] [force] [model=…] [effort=…] [dry] [補足の指示…] … /na-go（ct-ship-loop を頼み、終わったら ct-finish を自動で頼む。fix は ct-fix-loop）
  fix・new: 流れを選ぶ（fix = 不具合・負荷の流れ。ct-analyze の後の知らせに推奨が出る）
  モデルと思考の深さは送るスキルからダッシュボードが選ぶ（server.py の MODEL_TABLE）。model=・effort= はその1回だけ上書きする
      python3 hub_watch.py --slot [off|on 枠…]                     … /na-slot（自動で割り当てる枠から外す・戻す。引数なしで表示）
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_redmine as hr  # noqa: E402  （dash_get を共有する）

SLOTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "slots.json")  # hub/slots.json
MARK = {"done": "✓", "running": "▶", "question": "?", "skip": "✗", "": "・"}


def fetch(refresh=False):
    return hr.dash_get("/api/watch" + ("?refresh=1" if refresh else ""))


def pad(text, width):
    """全角を2桁として width 桁まで空白で埋める（ラベルの縦をそろえる）"""
    import unicodedata
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(width - w, 0)


def flow_lines(flow, per=3):
    """流れの印を per 個ずつの行に分ける（1行に並べると折り返して読みにくい。2026-11-25 ユーザー指定で縦に整形）"""
    marks = [(f"({x['short']}" if x["optional"] else x["short"]) + MARK.get(x["mark"], "") + (")" if x["optional"] else "")
             for x in flow or []]
    return [" ".join(marks[k:k + per]) for k in range(0, len(marks), per)]


def item_block(i, d, k=None):
    """1チケット分を「見出し＋ラベル付きの行」で返す。/na-watch と /na-list 枠 で使う"""
    slot = f" [{i['slot']}]" if i.get("slot") is not None else ""
    head = ("👀 " if i.get("attention") else "") + (f"{k}. " if k else "")
    out = [f"{head}#{i['id']}【{i.get('priority') or '?'}】{i.get('status', '')}{slot} {i['state_label']}"
           + (f" · {i['skill'].removeprefix('ct-')}" if i.get("skill") else "")]
    row = lambda label, text: out.append(f"  {pad(label, 6)}{text}")
    row("件名", hr_trim(i.get("subject", ""), 48))
    for n, ln in enumerate(flow_lines(i.get("flow"))):
        row(("流れ" if i.get("flow_kind") != "fix" else "不具合") if n == 0 else "", ln)
    if i.get("fix"):
        row("施策", i["fix"].get("display", ""))
    if i.get("flow_hint"):
        row("推奨", f"不具合・負荷の流れ（/na-go {i['id']} fix）" if i["flow_hint"] == "fix" else f"新規開発の流れ（/na-next {i['id']}）")
    if i.get("phase"):
        row("実装", f"フェーズ {i['phase']['done']}/{i['phase']['total']}")
    if i.get("pr_turn"):
        row("PR", "pr-turn " + ("済み" if i["pr_turn"]["result"] == "done" else "途中"))
    for p in i.get("prs") or []:
        row("PR", f"{p.get('repo', '')}#{p.get('number')} {p.get('state', '')}")
    if i.get("review"):
        row("依頼", i["review"]["label"])
    a = (d.get("auto") or {}).get(i["id"])
    if a:
        last = a.get("last") or {}
        # 今日より前の依頼は日付も出す（「18:55」だけだと今日のことに見えた。2026-11-26）
        when = time.strftime("%H:%M" if time.strftime("%Y%m%d", time.localtime(last.get("at") or 0)) == time.strftime("%Y%m%d") else "%m/%d %H:%M", time.localtime(last.get("at") or 0)) if last else ""
        row("自動", f"[{a.get('slot')}] " + (f"{last.get('skill', '').removeprefix('ct-')} {'送信' if last.get('ok') else '失敗'} {when}" if last else "開始"))
        if a.get("go"):
            row("", "実装: " + {"ship-loop": "ship-loop 中", "finish": "finish 中", "fix-loop": "fix-loop 中", "done": "完了"}.get(a["go"].get("stage"), a["go"].get("stage", "")))
    return out


def compact_text(d):
    items = d.get("items") or []
    dk = d.get("docker") or {}
    dq = dk.get("queue") or []
    dline = ""
    if dk.get("holders") or dk.get("holder") or dq:
        import hub_popup
        dline = ("開発用サーバー: " + hub_popup.docker_line(dk)
                 + ("・待ち " + " → ".join(f"#{q['ticket']}（{q['env']}）" for q in dq) if dq else ""))
    if not items:
        return (dline + "\n" if dline else "") + "固定したチケットはありません（/na-order 番号 … で固定すると監視します）"
    at = time.strftime("%H:%M", time.localtime(d.get("at") or time.time()))
    out = [f"{len(items)} 件・確認待ち {d.get('attention', 0)}（{at} 時点）"] + ([dline] if dline else [])
    for k, i in enumerate(items, 1):
        out.append("")
        out += item_block(i, d, k if len(items) > 1 else None)
    return "\n".join(out)


def hr_trim(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def dash_post(path, body):
    with open(os.path.join(hr.DASH_DIR, "config.json"), encoding="utf-8") as f:
        key = json.load(f).get("key", "")
    req = urllib.request.Request(hr.DASH_BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Cookie": f"dd_key={key}", "X-Dashboard": "1", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def model_args(args):
    """model=…・effort=… を取り出す。({"model":…, "effort":…}, 残りの引数)"""
    opt, rest = {}, []
    for a in args:
        k, _, v = a.partition("=")
        if k in ("model", "effort") and v:
            opt[k] = v.lower()
        else:
            rest.append(a)
    return opt, rest


def split_note(args, words):
    """先頭から決まった形の引数（番号・枠・words・model=・effort=・--branch 名前・branch=）を読み、
    最初に形の違う語が出た所から後ろを「補足の指示」として返す。(引数, 補足)。
    例: /na-next 15018 1 15026と内容が被ってるので先にそれを確認して → 補足は「15026と内容が…」（2026-11-25 補足が [1] に届かなかった）"""
    head, seen = [], set()
    for k, a in enumerate(args):
        if re.fullmatch(r"#?\d+", a):
            kind = "ticket" if len(a.lstrip("#")) >= 4 else "slot"
            if kind in seen:  # 2つ目の番号（/na-next 15018 1 15026 と被ってる）は補足の一部
                return head, " ".join(args[k:])
            seen.add(kind)
            head.append(a)
        elif a in words or a.split("=", 1)[0] in ("model", "effort", "branch", "--branch"):
            head.append(a)
        elif head and head[-1] == "--branch":
            head.append(a)
        else:
            return head, " ".join(args[k:])
    return head, ""


def next_cmd(args):
    """/na-next 番号 [枠] [sweep] [scope] [prod|noprod] [model=…] [effort=…] [dry] [補足の指示…]
    prod・noprod: ct-analyze に本番の DB・Redis・ログの精査を含めるか（本番の問題と自動で判断したチケットは、最初の1回だけ聞いて止まる）"""
    args, note = split_note(args, ("sweep", "scope", "dry", "prod", "noprod", "fix", "new"))
    opt, args = model_args(args)
    nums = [a for a in args if re.fullmatch(r"#?\d+", a)]
    tickets = [a.lstrip("#") for a in nums if len(a.lstrip("#")) >= 4]
    slots = [int(a) for a in nums if len(a.lstrip("#")) <= 2]
    if len(tickets) > 1 or len(slots) > 1 or (not tickets and not slots):
        return "⛔ 書き方: /na-next 番号 [枠] [sweep] [scope] [補足の指示]・/na-next 枠（その枠の作業中のチケット）（例: /na-next 14926・/na-next 14926 7・/na-next 14926 sweep scope）"
    r = dash_post("/api/watch/next", {"ticket": tickets[0] if tickets else None, "slot": slots[0] if slots else None,
                                     "sweep": "sweep" in args, "scope": "scope" in args, "dry": "dry" in args, "note": note,
                                     "prod": True if "prod" in args else (False if "noprod" in args else None),
                                     "flow": "fix" if "fix" in args else ("new" if "new" in args else None), **opt})
    return r.get("msg") if r.get("ok") else f"⛔ 送っていません: {r.get('msg') or r.get('error')}"


def go_cmd(args):
    """/na-go 番号 [枠] [--branch 名前|branch=名前] [force] [model=…] [effort=…] [dry] [補足の指示…]"""
    args, note = split_note(args, ("force", "dry", "fix", "new"))
    opt, args = model_args(args)
    branch, rest = "", []
    it = iter(args)
    for a in it:
        if a == "--branch":
            branch = next(it, "")
        elif a.startswith(("--branch=", "branch=")):
            branch = a.split("=", 1)[1]
        else:
            rest.append(a)
    nums = [a for a in rest if re.fullmatch(r"#?\d+", a)]
    tickets = [a.lstrip("#") for a in nums if len(a.lstrip("#")) >= 4]
    slots = [int(a) for a in nums if len(a.lstrip("#")) <= 2]
    if len(tickets) > 1 or len(slots) > 1 or (not tickets and not slots):
        return "⛔ 書き方: /na-go 番号 [枠] [--branch 名前] [force]・/na-go 枠（その枠の作業中のチケット）（例: /na-go 14926・/na-go 14926 5 --branch feature/14926_2）"
    r = dash_post("/api/watch/go", {"ticket": tickets[0] if tickets else None, "slot": slots[0] if slots else None, "branch": branch,
                                   "force": "force" in rest, "dry": "dry" in rest, "note": note,
                                   "flow": "fix" if "fix" in rest else ("new" if "new" in rest else None), **opt})
    return r.get("msg") if r.get("ok") else f"⛔ 送っていません: {r.get('msg') or r.get('error')}"


def slot_cmd(args):
    """/na-slot [off|on 枠…]: 自動で割り当てる枠から外す・戻す（hub/slots.json）"""
    try:
        with open(SLOTS_FILE, encoding="utf-8") as f:
            off = set(json.load(f).get("off") or [])
    except (OSError, ValueError):
        off = set()
    if args:
        op, nums = args[0], [int(a) for a in args[1:] if a.isdigit()]
        if op not in ("off", "on") or not nums or any(not 1 <= n <= 12 for n in nums):
            return "⛔ 書き方: /na-slot off 11 12・/na-slot on 11（引数なしで表示）"
        off = off | set(nums) if op == "off" else off - set(nums)
        tmp = SLOTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"off": sorted(off), "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, f, ensure_ascii=False)
        os.replace(tmp, SLOTS_FILE)
    return "自動で割り当てない枠: " + (" ".join(f"[{n}]" for n in sorted(off)) if off else "なし")


def run(args):
    refresh = any(a in ("--refresh", "refresh", "再取得") for a in args)
    d = fetch(refresh)
    if "--json" in args:
        return json.dumps(d, ensure_ascii=False, indent=1)
    return compact_text(d)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--next"]:
        print(next_cmd(a[1:]))
    elif a[:1] == ["--go"]:
        print(go_cmd(a[1:]))
    elif a[:1] == ["--slot"]:
        print(slot_cmd(a[1:]))
    else:
        print(run(a))
