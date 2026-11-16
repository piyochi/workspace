"""Codex の作業完了を待ち、指定ファイルがあれば中身を表示する。

使い方: python3 codex_wait.py <pane_id> [結果ファイル ...]
画面に "Working (" が3回続けて出なくなったら完了とみなす（一瞬の再描画で誤判定しないため）。
"""
import os
import subprocess
import sys
import time


def busy(pane):
    out = subprocess.run(["tmux", "capture-pane", "-p", "-t", pane, "-S", "-10"],
                         capture_output=True, text=True).stdout
    return "Working (" in out


def main():
    pane = sys.argv[1]
    idle = 0
    while idle < 3:
        idle = 0 if busy(pane) else idle + 1
        time.sleep(10)
    print("done")
    for path in sys.argv[2:]:
        print(f"===== {path}")
        if os.path.exists(path):
            print(open(path, encoding="utf-8").read())
        else:
            print("(ファイルなし)")


main()
