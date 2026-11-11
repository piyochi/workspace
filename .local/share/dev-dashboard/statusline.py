#!/usr/bin/env python3
"""Claude Code の statusLine コマンド。

Claude Code から渡される JSON のうち rate_limits（5時間枠・週の使用率）を
アカウント（設定フォルダ）ごとに cache/claude-<key>.json へ書き出し、
画面下には短い1行を出す。ダッシュボード（server.py）はこの cache を読む。
"""
import hashlib
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "cache")


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def account_label(cdir):
    """設定フォルダに対応する .claude.json の oauthAccount からメールを読む（無ければフォルダ名）。"""
    default = os.path.expanduser("~/.claude")
    candidates = [os.path.join(cdir, ".claude.json")]
    if os.path.normpath(cdir) == default:
        candidates.insert(0, os.path.expanduser("~/.claude.json"))
    for path in candidates:
        try:
            with open(path) as f:
                acct = json.load(f).get("oauthAccount") or {}
            if acct.get("emailAddress"):
                return acct["emailAddress"]
        except (OSError, ValueError):
            continue
    return os.path.basename(os.path.normpath(cdir))


def current_pane():
    """今の Claude が表示されている tmux の枠（%番号）。分からなければ ""。

    環境変数 TMUX_PANE が無いとき（セッションの実行が daemon の作業用プロセス claude bg-spare に移ると渡らない）は、
    親プロセスをたどり、tmux の枠と同じ端末（tty）を持つプロセスの枠を使う（~/bin/tmux-ai-state と同じ決め方）。
    """
    pane = os.environ.get("TMUX_PANE", "")
    if pane:
        return pane
    try:
        out = subprocess.run(["tmux", "list-panes", "-a", "-F", "#{pane_tty} #{pane_id}"],
                             capture_output=True, text=True, timeout=3).stdout
        panes = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
        pid = os.getppid()
        for _ in range(10):
            info = subprocess.run(["ps", "-o", "ppid=,tty=", "-p", str(pid)],
                                  capture_output=True, text=True, timeout=3).stdout.split()
            if len(info) < 2:
                break
            ppid, tty = info[0], info[1]
            if tty != "??" and f"/dev/{tty}" in panes:
                return panes[f"/dev/{tty}"]
            if not ppid.isdigit() or int(ppid) <= 1:
                break
            pid = int(ppid)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return ""


def pct(window):
    if not isinstance(window, dict):
        return None
    for k in ("used_percentage", "used_percent", "utilization"):
        if isinstance(window.get(k), (int, float)):
            return float(window[k])
    return None


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    os.makedirs(CACHE, exist_ok=True)

    # 受け取った JSON の形（キーと rate_limits）を残す。項目名が変わったときの確認用
    try:
        with open(os.path.join(CACHE, "last-input-shape.json"), "w") as f:
            json.dump({"keys": sorted(data.keys()), "rate_limits": data.get("rate_limits")}, f)
    except OSError:
        pass

    # どの tmux の枠でどのセッションが動いているかを残す（ダッシュボードがチケット番号を引くのに使う）
    pane = current_pane()
    if pane and data.get("transcript_path"):
        try:
            tmp = os.path.join(CACHE, f".pane-{pane.lstrip('%')}.tmp")
            with open(tmp, "w") as f:
                json.dump({"pane": pane, "session_id": data.get("session_id"),
                           "transcript_path": data["transcript_path"], "updated_at": time.time()}, f)
            os.replace(tmp, os.path.join(CACHE, f"pane-{pane.lstrip('%')}.json"))
        except OSError:
            pass

    cdir = config_dir()
    key = hashlib.sha1(os.path.normpath(cdir).encode()).hexdigest()[:10]
    limits = data.get("rate_limits")
    if limits:
        out = {
            "config_dir": cdir,
            "label": account_label(cdir),
            "rate_limits": limits,
            "updated_at": time.time(),
        }
        tmp = os.path.join(CACHE, f".claude-{key}.tmp")
        with open(tmp, "w") as f:
            json.dump(out, f)
        os.replace(tmp, os.path.join(CACHE, f"claude-{key}.json"))

    # --then <コマンド>: 画面の1行は既存のステータスラインに任せる（同じ JSON を渡して出力をそのまま出す）
    if len(sys.argv) >= 3 and sys.argv[1] == "--then":
        try:
            res = subprocess.run(sys.argv[2:], input=raw, capture_output=True, text=True, timeout=10)
            sys.stdout.write(res.stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return

    parts = []
    model = (data.get("model") or {}).get("display_name")
    if model:
        parts.append(model)
    if limits:
        five, week = pct(limits.get("five_hour")), pct(limits.get("seven_day"))
        if five is not None:
            parts.append(f"5h {five:.0f}%")
        if week is not None:
            parts.append(f"週 {week:.0f}%")
    print(" | ".join(parts))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # ステータスラインの失敗で Claude の画面を壊さない
        print("")
