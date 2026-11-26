#!/usr/bin/env python3
"""hub の /na-list・/na-watch・/na-redmine をポップアップ（tmux display-popup + less -R）で見せるための描き方。

hook の文は Claude Code が必ず黄色の1色で出すので読みにくい（2026-11-25 ユーザー）。ここでは hook 用の文を後から色付けせず、
データから直接、見出し・区切り線・桁をそろえた表・段階ごとの色で組み立てる。

  render_watch(d)           /na-watch   … チケットごとのカード（見出し・件名・流れ・実装/自動）
  render_slots(rows)        /na-list    … 枠の表（枠・状態・チケット・環境・ブランチ・会話・完了・最後の応答）
  render_slot(slot, n)      /na-list 枠 … 枠のカード＋監視のカード＋画面（枠の色のまま）
  render_redmine(text)      /na-redmine … hub_redmine の文に見出しと色だけ付ける
"""
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

E = "\x1b["
RST, BOLD, DIM = E + "0m", E + "1m", E + "2m"
FG = {"green": E + "38;5;114m", "cyan": E + "38;5;81m", "red": E + "38;5;203m", "yellow": E + "38;5;221m",
      "gray": E + "38;5;245m", "dark": E + "38;5;240m", "white": E + "38;5;255m", "blue": E + "38;5;111m"}
BG_HEAD = E + "48;5;236m"
MAX_W = 140
STATE_COLOR = {"処理中": "yellow", "busy": "yellow", "確認待ち": "red", "wait": "red", "質問中": "red", "question": "red",
               "入力待ち": "green", "idle": "green", "次の指示": "cyan", "next": "cyan", "未起動": "dark", "none": "gray"}
PRIO_COLOR = {"今すぐ": "red", "急いで": "yellow", "高め": "cyan", "通常": "gray", "低め": "dark"}


def width():
    """ポップアップの中の桁数（hub のクライアントの幅の 92% から枠と余白を引く）"""
    try:
        w = int(subprocess.run(["tmux", "display", "-p", "#{client_width}"], capture_output=True, text=True, timeout=3).stdout.strip())
        return max(60, min(int(w * 0.92) - 6, MAX_W))  # 広すぎると右寄せの項目が遠くなるので上限を付ける
    except (OSError, ValueError, subprocess.SubprocessError):
        return shutil.get_terminal_size((120, 40)).columns - 4


def dw(s):
    """表示幅（全角=2。色の制御文字は数えない）"""
    s = re.sub(r"\x1b\[[0-9;]*m", "", s)
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else (0 if unicodedata.combining(c) else 1) for c in s)


def pad(s, w):
    return s + " " * max(w - dw(s), 0)


def trim(s, w):
    """表示幅 w に収まるよう末尾を … にする（色の無い文字列用）"""
    if dw(s) <= w:
        return s
    out = ""
    for c in s:
        if dw(out + c) > w - 1:
            break
        out += c
    return out + "…"


def c(color, s):
    return FG[color] + s + RST


def state_color(label):
    for k, v in STATE_COLOR.items():
        if k in (label or ""):
            return v
    return "white"


def rule(w, title=""):
    if not title:
        return c("dark", "─" * w)
    return c("dark", "── ") + BOLD + title + RST + " " + c("dark", "─" * max(w - dw(title) - 4, 0))


def header(title, right, w):
    """1行目の帯（背景色付き）"""
    body = " " + BOLD + title + RST + BG_HEAD + "  " + c("gray", right) + BG_HEAD
    return BG_HEAD + pad(body, w) + RST


# ---- /na-watch -------------------------------------------------------------------------------

def flow_line(flow):
    """流れを1行に: 済み 緑・実行中 水色太字・質問中 赤太字・記録なし 灰の取り消し線・未実行 暗い灰。省略可は ( )"""
    parts = []
    for x in flow or []:
        name, m = x["short"], x["mark"]
        if m == "done":
            s = c("green", "✓ " + name)
        elif m == "running":
            s = BOLD + c("cyan", "▶ " + name)
        elif m == "question":
            s = BOLD + c("red", "? " + name)
        elif m == "skip":
            s = c("dark", E + "9m" + name + RST)
        else:
            s = c("dark", "· " + name)
        parts.append(c("dark", "(") + s + c("dark", ")") if x["optional"] else s)
    return c("dark", " → ").join(parts)


def ticket_card(i, d, w, num=None):
    pri = i.get("priority") or "?"
    st = i.get("state_label", "")
    slot = f"[{i['slot']}]" if i.get("slot") is not None else "枠なし"
    left = (c("red", "● ") if i.get("attention") else "  ") + (c("gray", f"{num}. ") if num else "") \
        + BOLD + c("white", f"#{i['id']}") + "  " + c(PRIO_COLOR.get(pri, "gray"), pri) + c("dark", " · ") + c("gray", i.get("status", ""))
    right = BOLD + slot + RST + " " + c(state_color(st), st) + (c("dark", " · ") + c("blue", i["skill"].removeprefix("ct-")) if i.get("skill") else "")
    out = [left + " " * max(w - dw(left) - dw(right), 2) + right]
    bar = c("dark", "  │ ")
    out.append(bar + trim(i.get("subject", ""), w - 6))
    out.append(bar)
    out.append(bar + flow_line(i.get("flow")))
    info = []
    if i.get("phase"):
        info.append(c("gray", "実装 ") + f"フェーズ {i['phase']['done']}/{i['phase']['total']}")
    for p in i.get("prs") or []:
        info.append(c("gray", "PR ") + f"{p.get('repo', '')}#{p.get('number')} {p.get('state', '')}")
    if i.get("pr_turn"):
        info.append(c("gray", "pr-turn ") + ("済み" if i["pr_turn"]["result"] == "done" else "途中"))
    if i.get("review"):
        info.append(c("red", "レビュー ") + i["review"]["label"])
    a = (d.get("auto") or {}).get(i["id"])
    if a:
        last = a.get("last") or {}
        if last:
            # 今日より前の依頼は日付も出す（「18:55」だけだと今日のことに見えた。2026-11-26）
            when = time.strftime("%H:%M" if time.strftime("%Y%m%d", time.localtime(last.get("at") or 0)) == time.strftime("%Y%m%d") else "%m/%d %H:%M", time.localtime(last.get("at") or 0))
            ok = c("green", "送信") if last.get("ok") else c("red", "失敗")
            info.append(c("gray", "自動 ") + f"[{a.get('slot')}] {last.get('skill', '').removeprefix('ct-')} {ok} {c('gray', when)}")
        else:
            info.append(c("gray", "自動 ") + "開始")
        if a.get("go"):
            info.append(c("gray", "実装の自動 ") + {"ship-loop": "ship-loop 中", "finish": "finish 中", "done": "完了"}.get(a["go"].get("stage"), a["go"].get("stage", "")))
    if info:
        out.append(bar + c("dark", "   ").join(info))
    return out


def render_watch(d):
    w = width()
    items = d.get("items") or []
    at = time.strftime("%H:%M", time.localtime(d.get("at") or time.time()))
    dk = d.get("docker") or {}
    h = dk.get("holder")
    srv = "開発用サーバー " + (f"使用中 #{h['ticket']}（{h['env']}）" if h else "空き") \
        + ("・待ち " + " → ".join(f"#{q['ticket']}" for q in dk.get("queue") or []) if dk.get("queue") else "")
    out = [header(f"監視  {len(items)} 件 · 確認待ち {d.get('attention', 0)}", f"{at} 時点   {srv}", w), ""]
    if not items:
        return "\n".join(out + ["  固定したチケットはありません（/na-order 番号 … で固定すると監視します）"])
    for k, i in enumerate(items, 1):
        out += ticket_card(i, d, w, k if len(items) > 1 else None) + [""]
    out.append(c("dark", "  ✓ 済み  ▶ 実行中  ? 質問中  · 未実行  ") + c("dark", E + "9m" + "取り消し線" + RST) + c("dark", " 記録なし  ( ) 省略可  ● 確認が要る"))
    return "\n".join(out)


# ---- /na-list ---------------------------------------------------------------------------------

def short_state(s):
    return re.sub(r"^\S+\s*", "", s or "")  # 「⏸ 入力待ち」→「入力待ち」（絵文字は幅がぶれるので外す）


def render_slots(rows):
    import hub_status as hs
    w = width()
    on = [r for r in rows if r["kind"] in ("claude", "codex")]
    off = [str(r["slot"]) for r in rows if r["kind"] not in ("claude", "codex")]
    out = [header(f"枠  起動 {len(on)} · 未起動 {len(off)}", time.strftime("%H:%M 時点"), w), ""]
    cols = [("枠", 5), ("状態", 10), ("チケット", 9), ("環境", 6), ("ブランチ", 22), ("会話", 12), ("完了", 6)]
    rest = max(w - sum(x for _, x in cols) - len(cols) * 2, 20)
    out.append("  " + "  ".join(c("gray", pad(n, x)) for n, x in cols) + "  " + c("gray", "最後の応答"))
    out.append("  " + rule(w - 2))
    for r in on:
        st = short_state(r["state"])
        vals = [BOLD + f"[{r['slot']}]" + RST, c(state_color(st), st), f"#{r['ticket']}" if r.get("ticket") else c("dark", "—"),
                r["env"], trim(hs.short_branch(r["branch"]), 22), r["ctx"], r["done"] or c("dark", "—")]
        last = trim(re.sub(r"\s+", " ", r["last"] or "").strip(), rest)
        line = "  " + "  ".join(pad(v, x) for v, (_, x) in zip(vals, cols)) + "  " + c("gray", last)
        out.append(line + ((" " + c("red", "🔒本番")) if r["prod"] else ""))
        if r.get("pending"):
            out.append("  " + " " * (sum(x for _, x in cols) + len(cols) * 2) + c("yellow", "未送信 ") + trim(r["pending"], rest - 7))
    if off:
        out += ["", c("dark", "  未起動: " + " ".join(f"[{n}]" for n in off))]
    return "\n".join(out)


def render_slot(slot, n=30):
    import hub_status as hs
    import hub_watch as hw
    w = width()
    rows = [r for r in hs.collect("monitor") if r["slot"] == slot]
    if not rows:
        return f"⛔ monitor タブに [{slot}] の枠がありません"
    r = rows[0]
    st = short_state(r["state"])
    out = [header(f"[{slot}]  {r['env']} {r['role']}", time.strftime("%H:%M 時点"), w), ""]
    kv = [("状態", c(state_color(st), st) + ((" " + c("red", "🔒本番")) if r["prod"] else "")),
          ("チケット", f"#{r['ticket']}" if r.get("ticket") else c("dark", "—"))]
    if r["kind"] in ("claude", "codex"):
        kv += [("ブランチ", hs.short_branch(r["branch"])), ("会話", r["ctx"] + (c("gray", f"   完了 {r['done']}") if r["done"] else ""))]
        if r.get("pending"):
            kv.append(("未送信", c("yellow", trim(r["pending"], w - 14))))
    for k, v in kv:
        out.append("  " + c("gray", pad(k, 10)) + v)
    if r["kind"] not in ("claude", "codex"):
        return "\n".join(out)
    try:  # 監視（/na-order で固定したチケット）のカード
        d = hw.fetch()
        mine = [i for i in d.get("items") or [] if i.get("slot") == slot or (r["ticket"] and str(i["id"]) == str(r["ticket"]))]
        if mine:
            out += ["", "  " + rule(w - 2, "監視")]
            for i in mine:
                out += [""] + ticket_card(i, d, w)
    except Exception:
        pass
    raw, plain = hs.capture_color(r["id"], max(n * 3, 80))
    out += ["", "  " + rule(w - 2, f"画面（末尾 {n} 行・{r['id']}）"), ""]
    out += [raw[k] + RST for k in hs.screen_rows(plain, n)]
    return "\n".join(out)


# ---- /na-redmine ------------------------------------------------------------------------------

def render_redmine(text):
    """hub_redmine の文（1件2行）に見出しの帯・区切り・色を付ける。中身の並びは変えない"""
    w = width()
    lines = text.splitlines()
    out = [header("Redmine", lines[0] if lines else "", w), ""]
    for ln in lines[1:]:
        if ln.startswith("── "):
            out += ([""] if out[-1] else []) + ["  " + rule(w - 2, ln.removeprefix("── ")), ""]
            continue
        m = re.match(r"^(\d+\. )?(#\d+) 【(.+?)】(\S+) (.*)$", ln)
        if m:
            body = m.group(5)
            mm = re.search(r"\s{2,}(\[\d+\].*)$", body)
            subj, work = (body[:mm.start()], mm.group(1)) if mm else (body, "")
            out.append("  " + (c("gray", m.group(1)) if m.group(1) else "") + BOLD + c("white", m.group(2)) + RST + "  "
                       + c(PRIO_COLOR.get(m.group(3), "gray"), m.group(3)) + c("dark", " · ") + c("gray", m.group(4)) + "  " + subj
                       + (("  " + c("cyan", work)) if work else ""))
        elif ln.strip():
            out.append("      " + c("gray", ln.strip()))
    return "\n".join(out)
