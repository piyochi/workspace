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
LIST_PREFIX = re.compile(r"^\s*/na-list(?:\s+(.*))?$")
REDMINE_PREFIX = re.compile(r"^\s*/na-redmine(?:\s+(.*))?$")
ORDER_PREFIX = re.compile(r"^\s*/na-order(?:\s+(.*))?$")
WATCH_PREFIX = re.compile(r"^\s*/na-watch(?:\s+(.*))?$")
NEXT_PREFIX = re.compile(r"^\s*/na-next(?:\s+(.*))?$")
SLOT_PREFIX = re.compile(r"^\s*/na-slot(?:\s+(.*))?$")
GO_PREFIX = re.compile(r"^\s*/na-go(?:\s+(.*))?$")
DRY_RUN = "--dry-run" in sys.argv  # 送信の直前で止める（条件の確認用）


class Refuse(Exception):
    pass


def find_slot(slot):
    for p in tl.load_panes("monitor"):
        m = hs.SLOT_RE.match(hs.slot_title(p["title"]))
        if m and int(m.group(1)) == slot:
            return p
    raise Refuse(f"monitor タブに [{slot}] の枠が見つかりません")


SENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sent")  # hub/sent/pane-<n>.json


def mark_sent(pane, text):
    """hub（MAIN）から送った印。枠の UserPromptSubmit hook（ticket_sessions.py）が「hub から来た指示か」を見分けるのに使う"""
    try:
        os.makedirs(SENT_DIR, exist_ok=True)
        with open(os.path.join(SENT_DIR, f"pane-{pane.lstrip('%')}.json"), "w", encoding="utf-8") as f:
            json.dump({"pane": pane, "text": text, "at": time.time()}, f, ensure_ascii=False)
    except OSError:
        pass  # 印が書けなくても送信は止めない（過去のセッションの確認が出ないだけ）


def send(args_text, busy_ok=False):
    """busy_ok: 処理中の枠にも送る（/na-to で手で打った指示。Claude Code は処理中の入力を今の処理の途中で読む。2026-11-25 ユーザー指定）。
    自動の依頼（/na-next・/na-go・autopilot）は /model・/effort を先に送るので、入力待ちのときだけ送る"""
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
    busy = busy_ok and info["state"] == "🔄 処理中"
    if info["state"] != "⏸ 入力待ち" and not busy:
        raise Refuse(f"{label} は {info['state']} なので送りません" + ("（確認の画面に文字を打つと選択肢を選んでしまうため。その枠で答えてください）" if "確認" in info["state"] else ""))
    if info["pending"]:
        raise Refuse(f"{label} の入力欄に未送信の文字「{hs.clip_tail(info['pending'], 30)}」が残っています。"
                     f"その枠で消すか送ってから、もう一度送ってください")
    # 入力待ちが続いているかを確かめる。処理の合間に一瞬だけ入力待ちに見えることがあり、そこで送ると「Queued」になる
    # （2026-11-25 [7] の ct-analyze の途中で本番精査の依頼が予約になった）。3 秒の間、1 秒ごとに入力待ち・入力欄が空のままかを見る
    for _ in range(0 if busy else 3):
        time.sleep(1.0)
        again = hs.parse_claude(hs.capture(p["id"]))
        if again["state"] != "⏸ 入力待ち":
            raise Refuse(f"{label} は {again['state']} なので送りません（入力待ちが続いていません）")
        if again["pending"]:
            raise Refuse(f"{label} の入力欄に未送信の文字「{hs.clip_tail(again['pending'], 30)}」が残っています")
    if DRY_RUN:
        return f"🧪 dry-run（送っていません）: {label} ← {hs.clip_tail(text, 60)}"
    # tmux_link.py send は「処理中」の表示が出るまで Enter を押し直して最大36秒待つ。
    # すぐ終わる返答だと待ち切ってしまうので、ここでは「入力欄が空になったか」で受け付けを判定する
    mark_sent(p["id"], text)
    tl.paste(p["id"], text)
    time.sleep(1.0)
    for attempt in range(2):  # 1回目の Enter が「/」の候補選択に使われた場合だけ、もう1回押す
        tl.tmux("send-keys", "-t", p["id"], "Enter")
        for _ in range(8):
            time.sleep(0.5)
            if not hs.parse_claude(hs.capture(p["id"]))["pending"]:
                return (f"✅ 送信しました{'（処理中の枠へ。今の処理の途中で読まれます）' if busy else ''}: {label} ← {hs.clip_tail(text, 60)}")
    raise Refuse(f"{label} に貼り付けましたが、入力欄に残ったままです。その枠の画面を確認してください")


def hook_main():
    data = json.load(sys.stdin)
    prompt = data.get("prompt", "")
    if LIST_PREFIX.match(prompt):
        # /na-list: 12枠の要約を画面に出すだけ（reason は会話に入らない）
        args = (LIST_PREFIX.match(prompt).group(1) or "").split()
        try:
            if args:
                # /na-list 枠 [行数]: その枠だけを詳しく（要約・監視の状態・画面の末尾。既定 30 行・最大 150 行）
                if not args[0].lstrip("[").rstrip("]").isdigit() or not 1 <= int(args[0].strip("[]")) <= 12 \
                        or (len(args) > 1 and not args[1].isdigit()):
                    raise Refuse("書き方: /na-list（Claude の枠の一覧）・/na-list 枠 [行数]（例: /na-list 7・/na-list 7 60）")
                n = min(int(args[1]), 150) if len(args) > 1 else 30
                msg = f"na-list [{args[0].strip('[]')}]\n" + hs.detail_text(int(args[0].strip("[]")), n)
            else:
                # hub が送るのは Claude の枠（奇数枠）だけなので、一覧も Claude の枠だけにする（2026-11-25 ユーザー指定）
                rows = [r for r in hs.collect("monitor") if r["slot"] % 2 == 1]
                msg = "na-list（Claude の枠）\n" + hs.compact_text(rows)
        except Refuse as e:
            msg = f"na-list ⛔ {e}"
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
    elif ORDER_PREFIX.match(prompt):
        # /na-order: /na-redmine の先頭に固定する順を hub だけで持つ（hub/order.json）
        args = (ORDER_PREFIX.match(prompt).group(1) or "").split()
        try:
            import hub_redmine as hr
            msg = "na-order " + hr.order_cmd(args)
        except Exception as e:
            msg = f"na-order ⛔ エラー（開発ダッシュボードが動いているか確認）: {type(e).__name__}: {e}"
    elif WATCH_PREFIX.match(prompt):
        # /na-watch [再取得]: 固定したチケットの枠・段階・状態（判定はダッシュボードの常駐ループ）
        args = (WATCH_PREFIX.match(prompt).group(1) or "").split()
        try:
            import hub_watch as hw
            msg = "na-watch " + hw.run(args)
        except Exception as e:
            msg = f"na-watch ⛔ エラー（開発ダッシュボードが動いているか確認）: {type(e).__name__}: {e}"
    elif GO_PREFIX.match(prompt):
        # /na-go 番号 [枠] [--branch 名前] [force]: ct-ship-loop を頼み、終わったら ct-finish を自動で頼む（E ができるまで1件ずつ）
        args = (GO_PREFIX.match(prompt).group(1) or "").split()
        try:
            import hub_watch as hw
            msg = "na-go " + hw.go_cmd(args)
        except Exception as e:
            msg = f"na-go ⛔ エラー（開発ダッシュボードが動いているか確認）: {type(e).__name__}: {e}"
    elif NEXT_PREFIX.match(prompt) or SLOT_PREFIX.match(prompt):
        # /na-next 番号 [枠] [sweep] [scope]: 次のスキルを頼み、以後は自動で頼む / /na-slot off|on 枠…: 自動で割り当てる枠の除外
        is_next = bool(NEXT_PREFIX.match(prompt))
        name = "na-next" if is_next else "na-slot"
        args = ((NEXT_PREFIX if is_next else SLOT_PREFIX).match(prompt).group(1) or "").split()
        try:
            import hub_watch as hw
            msg = f"{name} " + (hw.next_cmd(args) if is_next else hw.slot_cmd(args))
        except Exception as e:
            msg = f"{name} ⛔ エラー（開発ダッシュボードが動いているか確認）: {type(e).__name__}: {e}"
    elif PREFIX.match(prompt):
        try:
            msg = "na-to " + send(PREFIX.sub("", prompt, count=1), busy_ok=True)
        except Refuse as e:
            msg = f"na-to ⛔ 送っていません: {e}"
        except Exception as e:  # hook が落ちてもプロンプトは Claude に渡さない
            msg = f"na-to ⛔ エラーで送っていません: {type(e).__name__}: {e}"
    else:
        return  # /na-to・/na-list・/na-redmine・/na-order・/na-watch・/na-next・/na-slot・/na-go 以外は何もしない（通常どおり Claude に渡す）
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
