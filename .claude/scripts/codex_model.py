#!/usr/bin/env python3
"""tmux の枠で動いている Codex の「今の会話だけ」のモデルと推論の深さを切り替える。

Codex の /model 画面を開き、画面に出た一覧から名前で選ぶ（矢印の回数を決め打ちしない）。
最後は「s session」で決めるので、~/.codex/config.toml の既定値は変えない。

使い方:
  codex_model.py show <ペイン>                       今のモデルと深さ
  codex_model.py set  <ペイン> --kind <種類>         依頼の種類から自動で選ぶ（下の KINDS）
  codex_model.py set  <ペイン> --model GPT-6-Astra --effort high
  codex_model.py kinds                               種類の一覧
ペインは %ID（tmux_link.py resolve で引く）。Codex が入力待ちのときだけ動く。
結果は JSON 1行。changed=false は「もう同じだった」。失敗したときはメニューを閉じて ok=false を返す。
"""
import argparse
import json
import re
import subprocess
import sys
import time

# 依頼の種類 → (モデル, 深さ)。Codex の使用量は OpenAI 側の枠なので、Claude の週の枠には効かない。
# 迷ったら impl。種類を増やすときはここに足す。
KINDS = {
    "light":  ("GPT-6.1-Sol", "low",    "決まった直し: lint・テストの直し・コメントの照合・指摘どおりの小さな修正"),
    "impl":   ("GPT-6.1-Sol", "medium", "普通の実装: ship-loop のフェーズ・範囲の決まった機能追加（既定）"),
    "deep":   ("GPT-6.1-Sol", "high",   "考える実装: 設計に関わる実装・難しい原因調査・レビュー指摘の照合や再設計"),
    "hardest": ("GPT-6-Astra", "high",  "いちばん難しいもの: deep で2回失敗した・並行処理やお金まわりの込み入った修正"),
}
EFFORT_LABEL = {"low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra high"}
FOOTER = re.compile(r"(GPT-[0-9][\w.\- ]*?)\s+(low|medium|high|xhigh|max|ultra)\b", re.I)
ITEM = re.compile(r"^\s*(›)?\s*(\d+)\.\s+(.+?)(?:\s{2,}|$)")


def tmux(*a):
    return subprocess.run(["tmux", *a], capture_output=True, text=True, timeout=5).stdout


def screen(pane):
    return tmux("capture-pane", "-p", "-t", pane)


def keys(pane, *k, literal=False):
    tmux("send-keys", "-t", pane, *(["-l"] if literal else []), *k)


def norm(s):
    return re.sub(r"[\s\-]", "", s.lower())


def current(pane):
    m = None
    for m in FOOTER.finditer(screen(pane)):
        pass
    return (m.group(1).strip(), m.group(2).lower()) if m else (None, None)


def wait_for(pane, text, sec=6):
    end = time.time() + sec
    while time.time() < end:
        s = screen(pane)
        if text in s:
            return s
        time.sleep(0.3)
    return None


def items(s, after):
    """after の見出しより下の番号付きの行を [(番号, 名前, カーソルか)] で返す。"""
    s = s[s.rfind(after):]
    out = []
    for line in s.split("\n"):
        m = ITEM.match(line)
        if m:
            name = re.sub(r"\s*\((current|default)\)", "", m.group(3)).strip()
            out.append((int(m.group(2)), name, bool(m.group(1))))
    return out


def move_to(pane, lst, want):
    cur = next((n for n, _, c in lst if c), None)
    if cur is None:
        raise RuntimeError("カーソルの位置が読めません")
    d = want - cur
    for _ in range(abs(d)):
        keys(pane, "Down" if d > 0 else "Up")
        time.sleep(0.25)


def set_model(pane, model, effort):
    if "Working (" in screen(pane):
        return {"ok": False, "error": "Codex が処理中です。入力待ちになってから切り替えてください"}
    before = current(pane)
    if before[0] and norm(before[0]) == norm(model) and before[1] == effort:
        return {"ok": True, "changed": False, "model": before[0], "effort": before[1]}
    try:
        keys(pane, "/model", literal=True)
        time.sleep(0.6)
        keys(pane, "Enter")
        s = wait_for(pane, "Select Model")
        if not s:
            raise RuntimeError("モデルの一覧が開きません")
        lst = items(s, "Select Model")
        hit = next((n for n, name, _ in lst if norm(name) == norm(model)), None)
        if hit is None:
            raise RuntimeError(f"一覧に {model} がありません: {[name for _, name, _ in lst]}")
        move_to(pane, lst, hit)
        keys(pane, "Enter")
        s = wait_for(pane, "Select Reasoning Level")
        if not s:
            raise RuntimeError("深さの一覧が開きません")
        lst = items(s, "Select Reasoning Level")
        label = EFFORT_LABEL[effort]
        hit = next((n for n, name, _ in lst if name.lower() == label.lower()), None)
        if hit is None:
            raise RuntimeError(f"深さの一覧に {label} がありません")
        move_to(pane, lst, hit)
        keys(pane, "s")  # 今の会話だけ（既定値は変えない）
        time.sleep(1.5)
    except Exception as e:  # noqa: BLE001
        for _ in range(2):  # 開いているメニューだけ閉じる（余分な Esc は「前の入力を編集」に入る）
            if "Select " not in screen(pane):
                break
            keys(pane, "Escape")
            time.sleep(0.4)
        return {"ok": False, "error": str(e), "model": before[0], "effort": before[1]}
    after = current(pane)
    ok = bool(after[0]) and norm(after[0]) == norm(model) and after[1] == effort
    return {"ok": ok, "changed": True, "model": after[0], "effort": after[1],
            "before": {"model": before[0], "effort": before[1]}}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("kinds")
    sh = sub.add_parser("show")
    sh.add_argument("pane")
    st = sub.add_parser("set")
    st.add_argument("pane")
    st.add_argument("--kind", choices=sorted(KINDS))
    st.add_argument("--model")
    st.add_argument("--effort", choices=sorted(EFFORT_LABEL))
    a = ap.parse_args()
    if a.cmd == "kinds":
        for k, (m, e, d) in KINDS.items():
            print(f"{k:8s} {m} {e:6s} {d}")
        return
    if a.cmd == "show":
        m, e = current(a.pane)
        print(json.dumps({"model": m, "effort": e}, ensure_ascii=False))
        return
    if a.kind:
        model, effort, _ = KINDS[a.kind]
    elif a.model and a.effort:
        model, effort = a.model, a.effort
    else:
        sys.exit("--kind か、--model と --effort の両方を指定してください")
    r = set_model(a.pane, model, effort)
    if a.kind:
        r["kind"] = a.kind
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
