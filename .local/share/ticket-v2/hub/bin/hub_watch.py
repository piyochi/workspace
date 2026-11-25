#!/usr/bin/env python3
"""hub の監視の表示（/na-watch・hub の Claude 用）。

判定は開発ダッシュボードの常駐ループ（server.py の watch_loop。20 秒ごと）が行い、/api/watch と
~/.local/share/ticket-v2/hub/watch.json に書く。ここはそれを読んで 1 件 2 行に整えるだけ。
対象は /na-order で固定したチケット（hub/order.json）。

1行目: 順・#番号【優先度】ステータス [枠] 状態 · スキル 件名
2行目: 流れ（redmine→analyze→architect→(sweep)→(scope)→planner→issue-docs→ship-loop→finish）の印・フェーズ・PR・レビュー
  印: ✓ 済み / ▶ 実行中・途中 / ? 質問中 / ✗ 記録なし（後の段階が先に動いた） / ・ 未実行（() は省略可の段階）

使い方: python3 hub_watch.py [--refresh|refresh] [--json]
      python3 hub_watch.py --next 番号 [枠] [sweep] [scope] [model=…] [effort=…] [dry] [補足の指示…]   … /na-next（止まっている所から次のスキルを頼み、以後は自動で頼む）
      python3 hub_watch.py --go 番号 [枠] [--branch 名前] [force] [model=…] [effort=…] [dry] [補足の指示…] … /na-go（ct-ship-loop を頼み、終わったら ct-finish を自動で頼む）
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


def compact_text(d):
    items = d.get("items") or []
    dk = d.get("docker") or {}
    dq = dk.get("queue") or []
    dline = ""
    if dk.get("holder") or dq:
        h = dk.get("holder")
        dline = ("開発用サーバー: " + (f"使用中 #{h['ticket']}（{h['env']}）" if h else "空き")
                 + ("・待ち " + " → ".join(f"#{q['ticket']}（{q['env']}）" for q in dq) if dq else "") + "\n")
    if not items:
        return dline + "固定したチケットはありません（/na-order 番号 … で固定すると監視します）"
    at = time.strftime("%H:%M:%S", time.localtime(d.get("at") or time.time()))
    out = [f"{len(items)} 件・確認待ち {d.get('attention', 0)}（{at} 時点）"] + ([dline.rstrip()] if dline else [])
    for k, i in enumerate(items, 1):
        slot = f"[{i['slot']}] " if i.get("slot") is not None else ""
        skill = f" · {i['skill'].removeprefix('ct-')}" if i.get("skill") else ""
        head = "👀" if i.get("attention") else "  "
        out.append(f"{head}{k}. #{i['id']}【{i.get('priority') or '?'}】{i.get('status', '')} {slot}{i['state_label']}{skill}  {hr_trim(i.get('subject', ''), 36)}")
        flow = " ".join((f"({x['short']}" if x["optional"] else x["short"]) + MARK.get(x["mark"], "") + (")" if x["optional"] else "")
                        for x in i.get("flow") or [])
        extra = []
        if i.get("phase"):
            extra.append(f"フェーズ {i['phase']['done']}/{i['phase']['total']}")
        if i.get("pr_turn"):
            extra.append("pr-turn " + ("済み" if i["pr_turn"]["result"] == "done" else "途中"))
        for p in i.get("prs") or []:
            extra.append(f"{p.get('repo', '')}#{p.get('number')} {p.get('state', '')}")
        if i.get("review"):
            extra.append(i["review"]["label"])
        a = (d.get("auto") or {}).get(i["id"])
        if a:
            last = a.get("last") or {}
            when = time.strftime("%H:%M", time.localtime(last.get("at") or 0)) if last else ""
            extra.append(f"自動: [{a.get('slot')}] " + (f"{last.get('skill', '').removeprefix('ct-')} {'送信' if last.get('ok') else '失敗'} {when}" if last else "開始"))
            if a.get("go"):
                extra.append("実装: " + {"ship-loop": "ship-loop 中", "finish": "finish 中", "done": "完了"}.get(a["go"].get("stage"), a["go"].get("stage", "")))
        out.append("     " + flow + ("  " + "・".join(extra) if extra else ""))
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
    """/na-next 番号 [枠] [sweep] [scope] [model=…] [effort=…] [dry] [補足の指示…]"""
    args, note = split_note(args, ("sweep", "scope", "dry"))
    opt, args = model_args(args)
    nums = [a for a in args if re.fullmatch(r"#?\d+", a)]
    tickets = [a.lstrip("#") for a in nums if len(a.lstrip("#")) >= 4]
    slots = [int(a) for a in nums if len(a.lstrip("#")) <= 2]
    if len(tickets) != 1 or len(slots) > 1:
        return "⛔ 書き方: /na-next 番号 [枠] [sweep] [scope] [補足の指示]（例: /na-next 14926・/na-next 14926 7・/na-next 14926 sweep scope）"
    r = dash_post("/api/watch/next", {"ticket": tickets[0], "slot": slots[0] if slots else None,
                                     "sweep": "sweep" in args, "scope": "scope" in args, "dry": "dry" in args, "note": note, **opt})
    return r.get("msg") if r.get("ok") else f"⛔ 送っていません: {r.get('msg') or r.get('error')}"


def go_cmd(args):
    """/na-go 番号 [枠] [--branch 名前|branch=名前] [force] [model=…] [effort=…] [dry] [補足の指示…]"""
    args, note = split_note(args, ("force", "dry"))
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
    if len(tickets) != 1 or len(slots) > 1:
        return "⛔ 書き方: /na-go 番号 [枠] [--branch 名前] [force]（例: /na-go 14926・/na-go 14926 5 --branch feature/14926_2）"
    r = dash_post("/api/watch/go", {"ticket": tickets[0], "slot": slots[0] if slots else None, "branch": branch,
                                   "force": "force" in rest, "dry": "dry" in rest, "note": note, **opt})
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
