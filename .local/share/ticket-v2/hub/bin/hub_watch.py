#!/usr/bin/env python3
"""hub の監視の表示（/na-watch・hub の Claude 用）。

判定は開発ダッシュボードの常駐ループ（server.py の watch_loop。20 秒ごと）が行い、/api/watch と
~/.local/share/ticket-v2/hub/watch.json に書く。ここはそれを読んで 1 件 2 行に整えるだけ。
対象は /na-order で固定したチケット（hub/order.json）。

1行目: 順・#番号【優先度】ステータス [枠] 状態 · スキル 件名
2行目: 流れ（redmine→analyze→architect→(sweep)→(scope)→planner→issue-docs→ship-loop→finish）の印・フェーズ・PR・レビュー
  印: ✓ 済み / ▶ 実行中・途中 / ? 質問中 / ✗ 記録なし（後の段階が先に動いた） / ・ 未実行（() は省略可の段階）

使い方: python3 hub_watch.py [--refresh|refresh] [--json]
"""
import json
import os
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_redmine as hr  # noqa: E402  （dash_get を共有する）

MARK = {"done": "✓", "running": "▶", "question": "?", "skip": "✗", "": "・"}


def fetch(refresh=False):
    return hr.dash_get("/api/watch" + ("?refresh=1" if refresh else ""))


def compact_text(d):
    items = d.get("items") or []
    if not items:
        return "固定したチケットはありません（/na-order 番号 … で固定すると監視します）"
    at = time.strftime("%H:%M:%S", time.localtime(d.get("at") or time.time()))
    out = [f"{len(items)} 件・確認待ち {d.get('attention', 0)}（{at} 時点）"]
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
            extra.append(f"📨 {i['review']['label']}")
        out.append("     " + flow + ("  " + "・".join(extra) if extra else ""))
    return "\n".join(out)


def hr_trim(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def run(args):
    refresh = any(a in ("--refresh", "refresh", "再取得") for a in args)
    d = fetch(refresh)
    if "--json" in args:
        return json.dumps(d, ensure_ascii=False, indent=1)
    return compact_text(d)


if __name__ == "__main__":
    print(run(sys.argv[1:]))
