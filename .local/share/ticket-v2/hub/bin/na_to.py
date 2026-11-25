#!/usr/bin/env python3
"""hub 用: monitor タブの Claude の枠（奇数枠）に指示を送る。`/na-to <枠> <指示>` の実体。

hub の UserPromptSubmit hook から --hook で呼ばれ、`/na-to ` で始まるプロンプトだけを処理して
送信した後にプロンプトを止める（hub の Claude を動かさない＝hub の会話を消費しない）。

使い方:
  python3 ~/.local/share/ticket-v2/hub/bin/na_to.py 3 /ct-redmine 14926   # 直接
  （hook）stdin に {"prompt": "/na-to 3 /ct-redmine 14926", ...}           # --hook

送らずに止めるもの: 偶数枠（Codex。各 Claude から送る）・Claude が起動していない枠・
処理中の枠・入力欄に未送信の文字が残っている枠・本番系の枠
"""
import json
import os
import re
import subprocess
import time
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_status as hs  # noqa: E402  （tmux_link の読み込みも hub_status 側で行う）

tl = hs.tl
PREFIX = re.compile(r"^\s*/na-to(?:\s+|$)")
LIST_PREFIX = re.compile(r"^\s*/na-list\s*$")
REDMINE_PREFIX = re.compile(r"^\s*/na-redmine(?:\s+(.*))?$")
DRY_RUN = "--dry-run" in sys.argv  # 送信の直前で止める（条件の確認用）


class Refuse(Exception):
    pass


def find_slot(slot):
    for p in tl.load_panes("monitor"):
        m = hs.SLOT_RE.match(p["title"] or "")
        if m and int(m.group(1)) == slot:
            return p
    raise Refuse(f"monitor タブに [{slot}] の枠が見つかりません")


def send(args_text):
    m = re.match(r"^(\d+)\s+(.+)$", args_text.strip(), re.DOTALL)
    if not m:
        raise Refuse("書き方: /na-to <枠番号> <指示>（例: /na-to 3 /ct-redmine 14926）")
    slot, text = int(m.group(1)), m.group(2).strip()
    if slot % 2 == 0:
        raise Refuse(f"[{slot}] は Codex の枠です。Codex には相方の Claude（[{slot - 1}]）から送ってください")
    p = find_slot(slot)
    label = f"{p['title']}（{p['id']}）"
    if p["prod"]:
        raise Refuse(f"{label} は本番系の枠なので送りません")
    if p["state"] != "claude":
        raise Refuse(f"{label} で Claude が起動していません（状態: {p['state']}）")
    info = hs.parse_claude(hs.capture(p["id"]))
    if info["state"] != "⏸ 入力待ち":
        raise Refuse(f"{label} は {info['state']} なので送りません")
    if info["pending"]:
        raise Refuse(f"{label} の入力欄に未送信の文字「{hs.clip_tail(info['pending'], 30)}」が残っています。"
                     f"その枠で消すか送ってから、もう一度送ってください")
    if DRY_RUN:
        return f"🧪 dry-run（送っていません）: {label} ← {hs.clip_tail(text, 60)}"
    # tmux_link.py send は「処理中」の表示が出るまで Enter を押し直して最大36秒待つ。
    # すぐ終わる返答だと待ち切ってしまうので、ここでは「入力欄が空になったか」で受け付けを判定する
    tl.paste(p["id"], text)
    time.sleep(1.0)
    for attempt in range(2):  # 1回目の Enter が「/」の候補選択に使われた場合だけ、もう1回押す
        tl.tmux("send-keys", "-t", p["id"], "Enter")
        for _ in range(8):
            time.sleep(0.5)
            if not hs.parse_claude(hs.capture(p["id"]))["pending"]:
                return f"✅ 送信しました: {label} ← {hs.clip_tail(text, 60)}"
    raise Refuse(f"{label} に貼り付けましたが、入力欄に残ったままです。その枠の画面を確認してください")


def hook_main():
    data = json.load(sys.stdin)
    prompt = data.get("prompt", "")
    if LIST_PREFIX.match(prompt):
        # /na-list: 12枠の要約を画面に出すだけ（reason は会話に入らない）
        try:
            # hub が送るのは Claude の枠（奇数枠）だけなので、一覧も Claude の枠だけにする（2026-11-25 ユーザー指定）
            rows = [r for r in hs.collect("monitor") if r["slot"] % 2 == 1]
            msg = "na-list（Claude の枠）\n" + hs.compact_text(rows)
        except Exception as e:
            msg = f"na-list ⛔ エラー: {type(e).__name__}: {e}"
    elif REDMINE_PREFIX.match(prompt):
        # /na-redmine [件数] [優先度…|高め以上] [再取得]: ダッシュボードの /api/redmine を読んで画面に出すだけ
        args = (REDMINE_PREFIX.match(prompt).group(1) or "").split()
        try:
            import hub_redmine as hr
            msg = "na-redmine " + hr.run(args)
        except Exception as e:
            msg = f"na-redmine ⛔ エラー（開発ダッシュボードが動いているか確認）: {type(e).__name__}: {e}"
    elif PREFIX.match(prompt):
        try:
            msg = "na-to " + send(PREFIX.sub("", prompt, count=1))
        except Refuse as e:
            msg = f"na-to ⛔ 送っていません: {e}"
        except Exception as e:  # hook が落ちてもプロンプトは Claude に渡さない
            msg = f"na-to ⛔ エラーで送っていません: {type(e).__name__}: {e}"
    else:
        return  # /na-to・/na-list・/na-redmine 以外は何もしない（通常どおり Claude に渡す）
    print(json.dumps({"decision": "block", "reason": msg, "suppressOriginalPrompt": True}, ensure_ascii=False))
    reset_pane_state()


def reset_pane_state():
    """プロンプトを止めると Stop の hook が来ず、枠の色が「処理中」（tmux-ai-state busy）のまま残る。
    同じ UserPromptSubmit の busy が後から走って上書きしないよう、2秒後に idle へ戻す（hook 自体は待たない）。"""
    state_cmd = os.path.expanduser("~/bin/tmux-ai-state")
    if not os.environ.get("TMUX_PANE") or not os.access(state_cmd, os.X_OK):
        return
    subprocess.Popen(["/bin/sh", "-c", f"sleep 2; '{state_cmd}' idle"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def main():
    if sys.argv[1:2] == ["--hook"]:
        hook_main()
        return
    try:
        print(send(" ".join(a for a in sys.argv[1:] if a != "--dry-run")))
    except Refuse as e:
        sys.exit(f"送っていません: {e}")


if __name__ == "__main__":
    main()
