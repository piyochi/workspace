#!/usr/bin/env python3
"""hub 用: monitor タブの12枠（環境1〜4の Claude / Codex）を1枠1行に要約して出す。

画面の全文は出さず、末尾から機械的に次を抜き出す（会話を膨らませないため）:
  状態（処理中 / 入力待ち / 確認待ち / 未起動）・ブランチ・チケット番号・会話の使用量・
  最後の完了時刻・入力欄に残っている未送信の文字・最後の応答の末尾

使い方:
  python3 ~/.local/share/ticket-v2/hub/bin/hub_status.py            # 12枠の表
  python3 ~/.local/share/ticket-v2/hub/bin/hub_status.py --active   # 起動中の枠だけ
  python3 ~/.local/share/ticket-v2/hub/bin/hub_status.py --json     # 機械向け
詳しく見たい枠だけ tmux_link.py read <%ID> で全文を読む。
"""
import argparse
import json
import os
import re
import subprocess
import sys

# tmux_link を import しても git 管理下の scripts/ に __pycache__ を作らない
sys.dont_write_bytecode = True

HUB_ROOT = os.environ.get("HUB_ROOT", os.path.expanduser("~/www/ticket_v2_hub"))
sys.path.insert(0, os.path.join(HUB_ROOT, ".claude/skills/ct-tmux-link/scripts"))
import tmux_link as tl  # noqa: E402

SLOT_RE = re.compile(r"^\[(\d+)\]\s*(env\d)?\s*(.*)$")


def slot_title(title):
    """枠のタイトルを [n] … の形にそろえる。claude-monitor のフォーカス表示では、フォーカスした枠が「★ FOCUS [n] …」になり、
    元の位置に移った別の枠（MAIN の hub など）が「[n] → left」になる。後者は [n] ではないので空にする
    （2026-11-25 [1] 宛ての送信が hub の枠 %3 を [1] と取り違えた。hub が処理中だったので送られなかった）。"""
    t = (title or "").replace("★ FOCUS ", "", 1)
    return "" if "→ left" in t else t
TICKET_RE = re.compile(r"#(\d{5})\b")
RULE_RE = re.compile(r"^\s*─{10,}\s*$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# 入力欄の「❯ 」直後が薄い文字（SGR 2）なら Claude Code の候補（例: \x1b[39m❯ \x1b[2mpushして\x1b[0m）
# ❯ の後ろは通常の空白ではなく NBSP（U+00A0）のことがある
DIM_PROMPT_RE = re.compile(r"❯[  ](?:\x1b\[[0-9;]*m)*?\x1b\[2m")
SUGGEST = "\x00SUGGEST\x00"
TAIL_CHARS = 70

# Claude Code
CL_CTX = re.compile(r"(\d+k)/(\d+k)\s*\((\d+)%\)")
CL_DONE = re.compile(r"^✻ .*?(?:done (\d{1,2}:\d{2}))?\s*$")
CL_CONFIRM = re.compile(r"Do you want to|Enter to select|❯ 1\. Yes|Esc to cancel", re.IGNORECASE)
# Codex
CX_CTX = re.compile(r"Context (\d+)% used")
CX_CONFIRM = re.compile(r"Would you like to run|Allow command|\(y\)es|Press enter to confirm", re.IGNORECASE)
CX_PLACEHOLDER = re.compile(r"^›\s*(Ask Codex to do anything|Find and fix|Explain this|Summarize|Implement|Write tests|Improve documentation)")


def capture(pane_id, lines=80):
    """色付き（-e）で取り、入力欄の薄い文字（Claude Code の次の入力の候補）だけ印 SUGGEST を付けて、残りの色は消す。"""
    raw = tl.run(["tmux", "capture-pane", "-p", "-e", "-J", "-t", pane_id, "-S", f"-{lines}"])
    out = []
    for line in raw.splitlines():
        line = DIM_PROMPT_RE.sub(lambda m: "❯ " + SUGGEST, line)
        out.append(ANSI_RE.sub("", line))
    return out


def clip_tail(text, n=TAIL_CHARS):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else "…" + text[-n:]


def last_paragraph(lines):
    """lines の末尾から、空行で区切られた最後の段落を1行にして返す。"""
    para = []
    for line in reversed(lines):
        if not line.strip():
            if para:
                break
            continue
        para.append(line.strip().lstrip("⏺•").strip())
    return " ".join(reversed(para))


def ticket_of(branches, title, lines):
    m = re.search(r"feature/(\d+)", branches)
    if m:
        return m.group(1)
    m = TICKET_RE.search(title)
    if m:
        return m.group(1)
    for line in reversed(lines):
        m = TICKET_RE.search(line)
        if m:
            return m.group(1)
    return ""


def parse_claude(lines):
    info = {"ctx": "", "done": "", "pending": "", "last": ""}
    text = "\n".join(lines)
    m = CL_CTX.search(text)
    if m:
        info["ctx"] = f"{m.group(1)}/{m.group(2)}"
    # 入力欄は最後の2本の罫線の間
    rules = [i for i, l in enumerate(lines) if RULE_RE.match(l)]
    body_end = len(lines)
    if len(rules) >= 2:
        a, b = rules[-2], rules[-1]
        box = " ".join(l.strip() for l in lines[a + 1:b]).lstrip("❯").strip()
        if box.startswith(SUGGEST):  # 候補は貼り付けると消えるので、未送信の入力として扱わない
            info["suggest"] = box[len(SUGGEST):].strip()
        else:
            info["pending"] = box
        body_end = a
        body_end = a
    body = lines[:body_end]
    done_idx = None
    for i in range(len(body) - 1, -1, -1):
        m = CL_DONE.match(body[i].strip())
        if m:
            done_idx = i
            info["done"] = m.group(1) or ""
            break
    if done_idx is not None:
        body = body[:done_idx]
    info["last"] = last_paragraph(body)
    tail = "\n".join(lines[-25:])
    if tl.PROFILES["claude"]["busy"].search(tail):
        info["state"] = "🔄 処理中"
    elif CL_CONFIRM.search(tail):
        info["state"] = "❓ 確認待ち"
    else:
        info["state"] = "⏸ 入力待ち"
    return info


def parse_codex(lines):
    info = {"ctx": "", "done": "", "pending": "", "last": ""}
    text = "\n".join(lines)
    m = CX_CTX.search(text)
    if m:
        info["ctx"] = f"{m.group(1)}%"
    # 入力欄は最後の「› 」行
    box_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("›"):
            box_idx = i
            break
    body = lines
    if box_idx is not None:
        if not CX_PLACEHOLDER.match(lines[box_idx]):
            info["pending"] = lines[box_idx].lstrip("›").strip()
        body = lines[:box_idx]
    m = None
    for line in reversed(body):
        m = re.search(r"Worked for .*?(\d{1,2}:\d{2})\s*$", line)
        if m:
            info["done"] = m.group(1)
            break
    # 「Model changed」等のシステム行を飛ばし、最後の実質的な応答段落を取る
    kept = [l for l in body if not re.search(r"^\s*•\s*Model changed|^\s*(only|─+)\s*$|^\s*Worked for", l)]
    info["last"] = last_paragraph(kept)
    tail = "\n".join(lines[-25:])
    if tl.PROFILES["codex"]["busy"].search(tail):
        info["state"] = "🔄 処理中"
    elif CX_CONFIRM.search(tail):
        info["state"] = "❓ 確認待ち"
    else:
        info["state"] = "⏸ 入力待ち"
    return info


def collect(tab):
    panes = tl.load_panes(tab)
    rows = []
    for p in panes:
        m = SLOT_RE.match(slot_title(p["title"]))
        if not m:
            continue
        row = {"slot": int(m.group(1)), "env": m.group(2) or "", "role": m.group(3).strip(),
               "id": p["id"], "kind": p["state"], "prod": p["prod"]}
        if p["state"] in ("claude", "codex"):
            lines = capture(p["id"])
            row.update(parse_claude(lines) if p["state"] == "claude" else parse_codex(lines))
            root = tl.env_root(p["path"], p["state"]) or p["path"]
            row["branch"] = tl.repo_branches(root)
            row["ticket"] = ticket_of(row["branch"], p["title"], lines)
        else:
            row.update({"state": "⚪ 未起動", "branch": "", "ticket": "", "ctx": "",
                        "done": "", "pending": "", "last": ""})
        rows.append(row)
    rows.sort(key=lambda r: r["slot"])
    return rows


def short_branch(b):
    return b.replace("ticket_v2_api: ", "api:").replace("ticket_v2: ", "app:").replace(" / ", " ")


def summary_line(rows):
    active = [r for r in rows if r["kind"] in ("claude", "codex")]
    states = {}
    for r in active:
        states[r["state"]] = states.get(r["state"], 0) + 1
    summary = " / ".join(f"{k} {v}" for k, v in states.items())
    return f"{len(rows)}枠中 起動 {len(active)}（{summary}）・未起動 {len(rows) - len(active)}"


def compact_text(rows):
    """画面に出すだけ（/na-list の hook の表示用）の見やすい形。表は崩れるので1枠2行のテキストにする。"""
    out = []
    idle = []
    for r in rows:
        if r["kind"] not in ("claude", "codex"):
            idle.append(str(r["slot"]))
            continue
        lock = " 🔒本番" if r["prod"] else ""
        ticket = f' #{r["ticket"]}' if r["ticket"] else ""
        pending = f' 未送信「{clip_tail(r["pending"], 30)}」' if r["pending"] else ""
        meta = " ".join(x for x in (r["ctx"], f'完了 {r["done"]}' if r["done"] else "") if x)
        out.append(f'[{r["slot"]:>2}] {r["state"]}{ticket} {r["env"]} {r["role"]}{lock} '
                   f'｜{short_branch(r["branch"])}｜{meta}{pending}')
        out.append(f'      └ {clip_tail(r["last"], 80)}')
    if idle:
        out.append(f'未起動: {", ".join(idle)}')
    out.append(summary_line(rows))
    return "\n".join(out)


RULE_RE = re.compile(r"^[─━]{10,}\s*$")


def screen_rows(lines, n):
    """画面の末尾 n 行の行番号（入力欄の罫線から下・末尾の空行・続く空行を除く）。/na-list 枠 の表示用"""
    end = len(lines)
    for k in range(len(lines) - 1, -1, -1):  # 最後の入力欄（罫線 → ❯/› の行）の上の罫線まで
        if RULE_RE.match(lines[k]) and k + 1 < len(lines) and re.match(r"^\s*[❯›]", lines[k + 1]):
            end = k
            break
    else:  # Codex の入力欄は罫線が無い: 最後の › の行から下を除く
        for k in range(len(lines) - 1, -1, -1):
            if re.match(r"^›", lines[k]):
                end = k
                break
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    rows, blank = [], False
    for k in range(max(0, end - n * 2), end):  # 空行は続けて出さない
        if not lines[k].strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        rows.append(k)
    return rows[-n:]


def screen_body(lines, n):
    return [lines[k].rstrip() for k in screen_rows(lines, n)]


def capture_color(pane_id, lines=80):
    """capture と同じ行数で、色を残した行（ポップアップ用）と消した行の組"""
    raw = tl.run(["tmux", "capture-pane", "-p", "-e", "-J", "-t", pane_id, "-S", f"-{lines}"]).splitlines()
    return raw, [ANSI_RE.sub("", l) for l in raw]


def detail_text(slot, n=30, tab="monitor", color=False):
    """/na-list 枠 [行数]: その枠の要約（ラベル付きの縦の形）・監視の状態（固定したチケットなら）・画面の末尾 n 行"""
    rows = [r for r in collect(tab) if r["slot"] == slot]
    if not rows:
        return f"⛔ {tab} タブに [{slot}] の枠がありません"
    r = rows[0]
    import hub_watch as hw
    row = lambda label, text: out.append(f"  {hw.pad(label, 10)}{text}") if text else None
    lock = " 🔒本番" if r["prod"] else ""
    out = [f"[{r['slot']}] {r['state']}" + (f" #{r['ticket']}" if r.get("ticket") else "") + f" {r['env']} {r['role']}{lock}"]
    if r["kind"] not in ("claude", "codex"):
        return "\n".join(out)
    row("ブランチ", short_branch(r["branch"]))
    row("会話", " ".join(x for x in (r["ctx"], f"完了 {r['done']}" if r["done"] else "") if x))
    row("未送信", clip_tail(r["pending"], 60) if r["pending"] else "")
    try:  # 監視（/na-order で固定したチケット）に載っていれば流れの段階も出す。ダッシュボードが止まっていても画面は出す
        d = hw.fetch()
        mine = [i for i in d.get("items") or [] if i.get("slot") == slot or (r["ticket"] and str(i["id"]) == str(r["ticket"]))]
        for i in mine:
            out += ["", "監視"] + hw.item_block(i, d)
    except Exception:
        pass
    out.append("")
    out.append(f"── 画面（末尾 {n} 行・{r['id']}）" + "─" * 30)
    if color:  # 画面は枠の色のまま（範囲は色を消した行で決め、同じ行番号の色付きの行を出す）
        raw, plain = capture_color(r["id"], max(n * 3, 80))
        out += [raw[k] + "\x1b[0m" for k in screen_rows(plain, n)]
    else:
        out += screen_body(capture(r["id"], max(n * 3, 80)), n)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tab", default="monitor")
    ap.add_argument("--active", action="store_true", help="起動中の枠だけ出す")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--compact", action="store_true", help="/na-list と同じ1枠2行の形")
    args = ap.parse_args()

    rows = collect(args.tab)
    if not rows:
        sys.exit(f"{args.tab} タブに [N] 付きの枠がありません")
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
        return
    if args.compact:
        print(compact_text(rows))
        return
    shown = [r for r in rows if r["kind"] in ("claude", "codex")] if args.active else rows
    print("| 枠 | %ID | 中身 | 状態 | #チケット | ブランチ | 会話 | 完了 | 未送信の入力 | 最後の応答（末尾） |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in shown:
        if r["kind"] not in ("claude", "codex"):
            print(f'| {r["slot"]} | {r["id"]} | {r["env"]} {r["role"]} | {r["state"]} | | | | | | |')
            continue
        lock = " 🔒本番" if r["prod"] else ""
        pending = f'「{clip_tail(r["pending"], 30)}」' if r["pending"] else ""
        if not pending and r.get("suggest"):
            pending = f'（候補「{clip_tail(r["suggest"], 30)}」・未入力）'
        print(f'| {r["slot"]} | {r["id"]} | {r["env"]} {r["role"]}{lock} | {r["state"]} | {r["ticket"]} '
              f'| {short_branch(r["branch"])} | {r["ctx"]} | {r["done"]} | {pending} | {clip_tail(r["last"])} |')
    print("\n" + summary_line(rows))


if __name__ == "__main__":
    main()
