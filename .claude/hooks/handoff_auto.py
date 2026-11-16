#!/usr/bin/env python3
"""ct-handoff を自動圧縮（autoCompactWindow）でも動かすための hook。

hook は Claude ではないので、引き継ぎの中身（完了・残作業・決めたこと）は書けない。
そこで次の場所で Claude を動かす／取りこぼしを拾う:

  stop         Stop。返事を書き終えた区切りで会話が STOP_TOKENS（40万）を超えていたら、終わるのを止めて
               「ct-handoff を保存し、圧縮してよい区切りか判断して」と差し戻す。圧縮待ちの印を付ける
  defer        Claude が「区切りが悪い」と判断したときに Bash で呼ぶ（`handoff_auto.py defer <session_id>`）。
               圧縮待ちの印を消し、次に返事を書き終えたときにもう一度判断させる
  idle         Notification(idle_prompt)。圧縮待ちの印があり、枠が入力待ちなら、tmux の枠に /compact を打ち込む
               （返事の後 約60秒入力がないと発火する。区切りで圧縮するため）
  nudge        PostToolUse・UserPromptSubmit。返事が終わらない長い自走の保険。会話が NUDGE_TOKENS（46万）を
               超えたら、1回だけ「ct-handoff を保存してから作業を続けて」と Claude に伝える
  precompact   PreCompact。圧縮の要約に ct-handoff と同じ項目を残すよう指示する（保存し損ねたときの保険）
  postcompact  PostCompact。要約を .claude/tmp/auto_compact_<session>.md に保存し、nudge の印を消す
  sessionstart SessionStart(compact)。圧縮の直後に ct-handoff の restore を実行するよう伝える

入力は hook の stdin（JSON）。失敗しても常に exit 0（作業も圧縮も止めない）。

~/.claude/settings.json への登録（"hooks" に足す。既存の hook がある event は配列に追記する）:
  "autoCompactWindow": 500000,            # トップレベル。この大きさで自動圧縮する（最後の砦）
  "Stop":             [{"hooks": [{"type": "command", "command": "python3 -I ~/.claude/hooks/handoff_auto.py stop", "timeout": 10}]}],
  "Notification":     [{"matcher": "idle_prompt", "hooks": [{"type": "command", "command": "python3 -I ~/.claude/hooks/handoff_auto.py idle", "timeout": 10}]}],
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

STOP_TOKENS = int(os.environ.get("HANDOFF_STOP_TOKENS", "400000"))
NUDGE_TOKENS = int(os.environ.get("HANDOFF_NUDGE_TOKENS", "460000"))
STATE_DIR = os.path.expanduser("~/.claude/tmp/handoff-auto")
TAIL_BYTES = 2_000_000
RESTORE_WINDOW_SEC = 6 * 3600  # これより古い引き継ぎファイルは今の作業のものとみなさない
PENDING_MAX_SEC = 3 * 3600  # これより古い圧縮待ちの印は捨てる（別の作業に移っている）


def flag_path(sid):
    return os.path.join(STATE_DIR, f"{sid}.nudged")


def pending_path(sid):
    return os.path.join(STATE_DIR, f"{sid}.compact-pending")


def clear_flags(sid):
    for p in (flag_path(sid), pending_path(sid)):
        try:
            os.remove(p)
        except OSError:
            pass


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


BAD_BREAK = ("区切りが悪いのは次のとき: 自分がユーザーに質問して答えを待っている（push の可否など）／"
             "Codex・バックグラウンドのコマンド・Monitor の結果を待っている／複数の手順の途中で、続きに細かい情報が要る。")


def stop(inp):
    """返事を書き終えたとき。40万を超えていたら、引き継ぎの保存と「区切りがいいか」の判断を Claude にさせる。

    印: saved（このサイクルで引き継ぎを保存済み）・pending（圧縮してよい。idle が /compact を打つ）。
    Claude が区切りが悪いと判断したら `defer` で pending を消す → 次に返事を書き終えたときにもう一度聞く。
    """
    if inp.get("stop_hook_active") or inp.get("agent_id"):
        return
    sid = inp.get("session_id") or ""
    if not sid:
        return
    tokens = context_tokens(inp.get("transcript_path") or "")
    if tokens < STOP_TOKENS:
        return
    # 「区切りがいい」の判断はその返事のときだけ有効。圧縮される前にユーザーが続けたら、印は古いので消して聞き直す
    try:
        os.remove(pending_path(sid))
    except OSError:
        pass
    os.makedirs(STATE_DIR, exist_ok=True)
    first = not os.path.exists(flag_path(sid))
    with open(flag_path(sid), "w") as f:
        f.write(str(tokens))
    with open(pending_path(sid), "w") as f:
        f.write(str(time.time()))
    defer_cmd = f"python3 -I ~/.claude/hooks/handoff_auto.py defer {sid}"
    if first:
        head = ("終える前に、ユーザーに確認せず ct-handoff スキルを引数「保存 auto」で実行して引き継ぎを保存してください。"
                "そのうえで、今が圧縮してよい区切りかを判断してください。")
    else:
        head = ("引き継ぎは保存済みで、まだ圧縮されていません。今が圧縮してよい区切りかを判断してください"
                "（引き継ぎに書くべき進展があれば、ct-handoff を引数「保存 auto」で実行して更新する）。")
    print(json.dumps({"decision": "block", "reason":
        f"[handoff-auto] 会話が約{tokens // 1000}kトークンです。{head}{BAD_BREAK}"
        f"区切りが悪ければ `{defer_cmd}` を実行して「圧縮は次の区切りに延ばします（理由）」の1行で終える。"
        "区切りがよければ「引き継ぎを保存しました: <パス>。約1分後に /compact が入ります」の1行で終える"
        "（直前の返事は繰り返さない）。"}, ensure_ascii=False))


def defer(sid):
    """Claude が「区切りが悪い」と判断したときに呼ぶ。圧縮待ちの印を消す（saved は残す）。"""
    sid = sid or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not sid:
        print("session id がありません")
        return
    try:
        os.remove(pending_path(sid))
        print("圧縮を次の区切りに延ばしました")
    except OSError:
        print("圧縮待ちの印はありませんでした")


def find_pane():
    """hook が動いている tmux の枠。TMUX_PANE が無いときは親プロセスの tty から探す（tmux-ai-state と同じ）。"""
    import subprocess
    pane = os.environ.get("TMUX_PANE", "")
    if pane:
        return pane
    try:
        rows = subprocess.run(["tmux", "list-panes", "-a", "-F", "#{pane_tty} #{pane_id}"],
                              capture_output=True, text=True, timeout=3).stdout.split("\n")
        ttys = dict(r.split(" ", 1) for r in rows if " " in r)
        p = os.getppid()
        for _ in range(10):
            out = subprocess.run(["ps", "-o", "tty=,ppid=", "-p", str(p)],
                                 capture_output=True, text=True, timeout=3).stdout.split()
            if len(out) < 2:
                break
            if out[0] not in ("", "??") and f"/dev/{out[0]}" in ttys:
                return ttys[f"/dev/{out[0]}"]
            p = int(out[1])
            if p <= 1:
                break
    except Exception:  # noqa: BLE001
        pass
    return ""


def idle(inp):
    import subprocess
    sid = inp.get("session_id") or ""
    p = pending_path(sid) if sid else ""
    if not p or not os.path.exists(p):
        return
    if time.time() - os.path.getmtime(p) > PENDING_MAX_SEC:
        os.remove(p)
        return
    pane = find_pane()
    if not pane:
        return
    # 入力待ち（tmux-ai-state の idle）のときだけ打ち込む。処理中・質問待ちなら次の機会に回す
    state = subprocess.run(["tmux", "show-options", "-pqv", "-t", pane, "@ai_state"],
                           capture_output=True, text=True, timeout=3).stdout.strip()
    if state not in ("idle", ""):
        return
    os.remove(p)
    subprocess.run(["tmux", "send-keys", "-t", pane, "-l", "/compact"], timeout=3)
    time.sleep(0.3)
    subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], timeout=3)


def precompact(inp):
    print("この要約は ct-handoff の引き継ぎとしても使う。次の項目を必ず残すこと: "
          "対象チケット番号と作業の目的／各リポジトリのブランチ・未コミット・未 push／"
          "完了したこと（コミットはハッシュ付き）／進行中のこと／次にやる残作業（ファイルパス・手順・成功基準）／"
          "ユーザーと決めた方針・禁止事項・待っている確認（push の可否など）。")


def postcompact(inp):
    sid = inp.get("session_id") or ""
    if sid:
        clear_flags(sid)
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
        clear_flags(sid)
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
    if mode == "defer":
        defer(sys.argv[2] if len(sys.argv) > 2 else "")
        return
    try:
        inp = json.load(sys.stdin)
    except ValueError:
        return
    fn = {"nudge": nudge, "stop": stop, "idle": idle, "precompact": precompact,
          "postcompact": postcompact, "sessionstart": sessionstart}.get(mode)
    if fn:
        fn(inp)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — hook は作業を止めない
        print(f"handoff-auto: {e}", file=sys.stderr)
    sys.exit(0)
