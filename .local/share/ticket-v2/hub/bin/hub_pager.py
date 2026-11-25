#!/usr/bin/env python3
"""hub のポップアップ用の小さなページャー（色付きの文をそのまま出す）。

less では Esc を「閉じる」に割り当てると、矢印キー（Esc で始まる信号）まで閉じてしまう（2026-11-25 試験）。
ここでは Esc の後 50ms 以内に続きが来なければ「Esc だけ」とみなして閉じる。

  キー: q・Esc・Ctrl-C 閉じる / ↑↓・j k・マウスのホイール 1行 / PgUp PgDn・Space b 1画面 / g・Home 先頭 / G・End 末尾 / ←→・h l 横
使い方: python3 hub_pager.py <ファイル> [--delete]（--delete は閉じたらファイルを消す）
"""
import os
import re
import select
import sys
import termios
import tty
import unicodedata

TOKEN = re.compile(r"(\x1b\[[0-9;?]*[A-Za-z])|(.)", re.S)


def cw(ch):
    return 2 if unicodedata.east_asian_width(ch) in "WF" else (0 if unicodedata.combining(ch) else 1)


def cut(line, left, width):
    """色の制御文字を保ったまま、表示桁 [left, left+width) の部分を返す"""
    out, col = [], 0
    for esc, ch in TOKEN.findall(line):
        if esc:
            out.append(esc)
            continue
        w = cw(ch)
        if col >= left and col + w <= left + width:
            out.append(ch)
        elif col < left < col + w:  # 全角の途中から始まるときは空白で埋める
            out.append(" ")
        col += w
    return "".join(out) + "\x1b[0m"


SEQ = {"[A": "UP", "OA": "UP", "[B": "DOWN", "OB": "DOWN", "[C": "RIGHT", "OC": "RIGHT", "[D": "LEFT", "OD": "LEFT",
       "[5~": "PGUP", "[6~": "PGDN", "[H": "HOME", "[1~": "HOME", "OH": "HOME", "[F": "END", "[4~": "END", "OF": "END"}
SEQ_RE = re.compile(r"\x1b(\[<(\d+);\d+;\d+[Mm]|\[[0-9;]*[A-Za-z~]|O[A-Za-z])")


def read_keys(fd):
    """押されたキーの一覧。続けて届いた分（矢印の連打・ホイール）もまとめて読む。Esc の後 50ms 何も来なければ "ESC" """
    data = os.read(fd, 1)
    while select.select([fd], [], [], 0.05)[0]:
        more = os.read(fd, 256)
        if not more:
            break
        data += more
    text, keys, k = data.decode(errors="ignore"), [], 0
    while k < len(text):
        m = SEQ_RE.match(text, k)
        if m:
            if m.group(2):
                keys.append({"64": "WHEELUP", "65": "WHEELDN"}.get(m.group(2), ""))
            else:
                keys.append(SEQ.get(m.group(1), ""))
            k = m.end()
        elif text[k] == "\x1b":
            keys.append("ESC")
            k += 1
        else:
            keys.append(text[k])
            k += 1
    return keys


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0]
    with open(path, encoding="utf-8") as f:
        lines = f.read().rstrip("\n").split("\n")
    if "--delete" in sys.argv:
        try:
            os.remove(path)
        except OSError:
            pass
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    out = sys.stdout
    top = left = 0
    try:
        tty.setraw(fd)
        out.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
        while True:
            cols, rows = os.get_terminal_size()
            body = max(rows - 1, 1)
            top = max(0, min(top, len(lines) - body))
            buf = ["\x1b[H"]
            for k in range(body):
                i = top + k
                buf.append("\x1b[2K" + (cut(lines[i], left, cols) if i < len(lines) else "") + ("\r\n" if k < body - 1 else ""))
            pos = f"{min(top + body, len(lines))}/{len(lines)} 行" if len(lines) > body else "全体"
            buf.append(f"\r\n\x1b[2K\x1b[2m q・Esc 閉じる   ↑↓ スクロール   ←→ 横   {pos}\x1b[0m")
            out.write("".join(buf))
            out.flush()
            keys = read_keys(fd)
            if any(k in ("q", "Q", "ESC", "\x03") for k in keys):
                break
            for k in keys:
                top = max(0, min(top, len(lines) - body))
                top += {"UP": -1, "k": -1, "WHEELUP": -3, "DOWN": 1, "j": 1, "WHEELDN": 3, "\r": 1,
                        "PGUP": -body, "b": -body, "PGDN": body, " ": body, "f": body}.get(k, 0)
                if k in ("HOME", "g"):
                    top = 0
                elif k in ("END", "G"):
                    top = len(lines)
                elif k in ("LEFT", "h"):
                    left = max(0, left - 8)
                elif k in ("RIGHT", "l"):
                    left += 8
    finally:
        out.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[?1049l")
        out.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
