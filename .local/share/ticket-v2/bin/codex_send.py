"""Codex のペインに依頼文を送り、動き出したことを確かめる。

使い方: python3 codex_send.py [--new] [--kind 種類] <pane_id> <依頼文ファイル>
  --new   依頼文を送る前に /new で新しい会話にする（作業の区切りで使う）。
          Codex が作業中なら送らずに終了する。
  --kind  依頼の種類（light / impl / deep / hardest）。送る前に、その種類のモデルと推論の深さに
          今の会話だけ切り替える（~/.claude/scripts/codex_model.py。既定値は変えない）。
          省略すると impl。/new すると Codex の設定は既定に戻るので、毎回この種類で合わせ直す。
          種類の一覧: python3 ~/.claude/scripts/codex_model.py kinds
許可プロンプトを避けるため、tmux 操作をこの1スクリプトにまとめている。
"""
import json
import os
import subprocess
import sys
import time

CODEX_MODEL = os.path.expanduser("~/.claude/scripts/codex_model.py")

# Codex 0.167.1 で確認: 新しい会話の入力欄が空のときに出る文言
EMPTY_PROMPT = "› Ask Codex to do anything"


def capture(pane, start=None):
    cmd = ["tmux", "capture-pane", "-p", "-t", pane]
    if start is not None:
        cmd += ["-S", start]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def busy(pane):
    return "Working (" in capture(pane, "-10")


def start_new_chat(pane):
    """/new を送り、空の入力欄に戻ったら True。"""
    if busy(pane):
        print("NOT sent: Codex が作業中のため /new を送りませんでした")
        sys.exit(1)
    subprocess.run(["tmux", "send-keys", "-t", pane, "-l", "/new"], check=True)
    time.sleep(1)
    for _ in range(3):
        subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], check=True)
        for _ in range(5):
            time.sleep(1)
            screen = capture(pane)
            if EMPTY_PROMPT in screen and "› /new" not in screen and not busy(pane):
                return True
    return False


def main():
    args = sys.argv[1:]
    new = "--new" in args
    args = [a for a in args if a != "--new"]
    kind = "impl"
    if "--kind" in args:
        i = args.index("--kind")
        kind = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__)
        sys.exit(2)
    pane, path = args
    text = open(path, encoding="utf-8").read().strip()
    if new:
        if not start_new_chat(pane):
            print("NOT sent: /new の後に入力待ちへ戻りませんでした。ペインを確認してください")
            sys.exit(1)
        print("new chat")
    if os.path.exists(CODEX_MODEL):
        r = subprocess.run([sys.executable, "-I", CODEX_MODEL, "set", pane, "--kind", kind],
                           capture_output=True, text=True)
        out = (r.stdout or r.stderr).strip()
        try:
            res = json.loads(out)
        except ValueError:
            res = {"ok": False, "error": out}
        if not res.get("ok"):
            print(f"NOT sent: モデルを {kind} に切り替えられませんでした: {res.get('error')}")
            sys.exit(1)
        print(f"model {kind}: {res.get('model')} {res.get('effort')}" + ("" if res.get("changed") else "（そのまま）"))
    subprocess.run(["tmux", "send-keys", "-t", pane, "-l", text], check=True)
    time.sleep(2)
    for _ in range(3):
        subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], check=True)
        for _ in range(6):
            time.sleep(2)
            if busy(pane):
                print("started")
                return
    print("NOT started: 入力欄を確認してください")
    sys.exit(1)


main()
