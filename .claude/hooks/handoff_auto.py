#!/usr/bin/env python3
"""ct-handoff を自動圧縮（autoCompactWindow）でも動かすための hook。

hook は Claude ではないので、引き継ぎの中身（完了・残作業・決めたこと）は書けない。
そこで次の4か所で Claude を動かす／取りこぼしを拾う:

  nudge        PostToolUse・UserPromptSubmit。会話が NUDGE_TOKENS を超えたら、
               1回だけ「ct-handoff を保存してから作業を続けて」と Claude に伝える
  precompact   PreCompact。圧縮の要約に ct-handoff と同じ項目を残すよう指示する（保存し損ねたときの保険）
  postcompact  PostCompact。要約を .claude/tmp/auto_compact_<session>.md に保存し、nudge の印を消す
  sessionstart SessionStart(compact)。圧縮の直後に ct-handoff の restore を実行するよう伝える

入力は hook の stdin（JSON）。失敗しても常に exit 0（作業も圧縮も止めない）。

~/.claude/settings.json への登録（"hooks" に足す。既存の hook がある event は配列に追記する）:
  "autoCompactWindow": 250000,            # トップレベル。この大きさで自動圧縮する
  "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 -I ~/.claude/hooks/handoff_auto.py nudge", "timeout": 10}]}],
  "PostToolUse":      [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 -I ~/.claude/hooks/handoff_auto.py nudge", "timeout": 10}]}],
  "PreCompact":       [{"matcher": "auto", "hooks": [{"type": "command", "command": "python3 -I ~/.claude/hooks/handoff_auto.py precompact", "timeout": 10}]}],
  "PostCompact":      [{"hooks": [{"type": "command", "command": "python3 -I ~/.claude/hooks/handoff_auto.py postcompact", "timeout": 10}]}],
  "SessionStart":     [{"matcher": "compact", "hooks": [{"type": "command", "command": "python3 -I ~/.claude/hooks/handoff_auto.py sessionstart", "timeout": 10}]}]
"""
import glob
import json
import os
import sys
import time

NUDGE_TOKENS = int(os.environ.get("HANDOFF_NUDGE_TOKENS", "330000"))
STATE_DIR = os.path.expanduser("~/.claude/tmp/handoff-auto")
TAIL_BYTES = 2_000_000
RESTORE_WINDOW_SEC = 6 * 3600  # これより古い引き継ぎファイルは今の作業のものとみなさない


def flag_path(sid):
    return os.path.join(STATE_DIR, f"{sid}.nudged")


def context_tokens(transcript):
    """transcript の末尾から、メイン会話の直近の呼び出しのコンテキスト量を読む。"""
    try:
        size = os.path.getsize(transcript)
        with open(transcript, "rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            lines = f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return 0
    for line in reversed(lines):
        if '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("isSidechain"):
            continue
        u = (d.get("message") or {}).get("usage")
        if u:
            return (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                    + u.get("cache_read_input_tokens", 0))
    return 0


def emit(event, text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
                     ensure_ascii=False))


def nudge(inp):
    if inp.get("agent_id"):  # サブエージェントの中では促さない
        return
    sid = inp.get("session_id") or ""
    if not sid or os.path.exists(flag_path(sid)):
        return
    tokens = context_tokens(inp.get("transcript_path") or "")
    if tokens < NUDGE_TOKENS:
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(flag_path(sid), "w") as f:
        f.write(str(tokens))
    emit(inp.get("hook_event_name", "PostToolUse"),
         f"[handoff-auto] 会話が約{tokens // 1000}kトークンになり、まもなく自動圧縮されます。"
         "今の手順の区切りで、ユーザーに確認せず ct-handoff スキルを引数「保存 auto」で実行して引き継ぎを保存し、"
         "/compact の案内は出さずにそのまま元の作業を続けてください。")


def precompact(inp):
    print("この要約は ct-handoff の引き継ぎとしても使う。次の項目を必ず残すこと: "
          "対象チケット番号と作業の目的／各リポジトリのブランチ・未コミット・未 push／"
          "完了したこと（コミットはハッシュ付き）／進行中のこと／次にやる残作業（ファイルパス・手順・成功基準）／"
          "ユーザーと決めた方針・禁止事項・待っている確認（push の可否など）。")


def postcompact(inp):
    sid = inp.get("session_id") or ""
    if sid:
        try:
            os.remove(flag_path(sid))
        except OSError:
            pass
    summary = inp.get("compact_summary")
    cwd = inp.get("cwd") or os.getcwd()
    if not summary or not sid:
        return
    out_dir = os.path.join(cwd, ".claude", "tmp")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"auto_compact_{sid[:8]}.md")
    with open(path, "w") as f:
        f.write(f"<!-- handoff-auto: {inp.get('trigger', '')} {time.strftime('%Y-%m-%d %H:%M')} -->\n")
        f.write("# 圧縮時の要約（自動保存）\n\n")
        f.write(summary)


def sessionstart(inp):
    if inp.get("source") != "compact":
        return
    sid = inp.get("session_id") or ""
    if sid:
        try:
            os.remove(flag_path(sid))
        except OSError:
            pass
    cwd = inp.get("cwd") or os.getcwd()
    now = time.time()
    waiting = []
    for p in glob.glob(os.path.join(cwd, ".claude", "tmp", "*session_handoff.md")):
        try:
            if now - os.path.getmtime(p) > RESTORE_WINDOW_SEC:
                continue
            with open(p, errors="ignore") as f:
                if "ct-handoff: awaiting-restore" in f.readline():
                    waiting.append(p)
        except OSError:
            continue
    if waiting:
        emit("SessionStart",
             "[handoff-auto] 圧縮の直後です。次の応答では最初に ct-handoff スキルを引数「続きから」で実行し、"
             f"引き継ぎ（{', '.join(sorted(waiting, key=os.path.getmtime, reverse=True))}）を読んで裏取りしてから元の作業を続けてください。")
    else:
        emit("SessionStart",
             "[handoff-auto] 圧縮の直後です。ct-handoff の引き継ぎは保存されていません。"
             f"要約の全文は {cwd}/.claude/tmp/auto_compact_{sid[:8]}.md にあります（PostCompact が保存できた場合）。"
             "git の状態を取り直してから作業を続けてください。")


def ctx():
    """スキルから呼ぶ: 今の会話の大きさ（トークン数）を出す。分からなければ 0。"""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    paths = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl")) if sid else []
    print(context_tokens(paths[0]) if paths else 0)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "ctx":
        ctx()
        return
    try:
        inp = json.load(sys.stdin)
    except ValueError:
        return
    fn = {"nudge": nudge, "precompact": precompact,
          "postcompact": postcompact, "sessionstart": sessionstart}.get(mode)
    if fn:
        fn(inp)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — hook は作業を止めない
        print(f"handoff-auto: {e}", file=sys.stderr)
    sys.exit(0)
