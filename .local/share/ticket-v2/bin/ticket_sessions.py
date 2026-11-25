#!/usr/bin/env python3
"""チケット番号が出てくる過去の Claude Code のセッションを探し、使うかどうかを ct-redmine の前に確かめるための道具。

bin/claude-history（tmux の C-r の fzf）の ctrl-o（セッションを開き直す）・ctrl-t（直近の会話を書き出して読ませる）と同じことを、
番号から直接行う。個人用（~/.claude/settings.json の UserPromptSubmit hook から呼ぶ。チームのスキルは変えない）。

  ticket_sessions.py --hook                    UserPromptSubmit hook。hub（MAIN）から送られた /ct-redmine 番号（参照だけ）のときに過去のセッションを探し、
                                               見つかれば「読み込む前に使うか確かめて」という指示を会話に足す
  ticket_sessions.py find 番号 [--exclude ID]  過去のセッションの一覧（新しい順）
  ticket_sessions.py handoff セッションID [往復数]  直近の会話（発言と返答の本文だけ）を Markdown に書き出してパスを出す（ctrl-t 相当）
  ticket_sessions.py resume セッションID        今の tmux の枠でそのセッションを開き直す（ctrl-o 相当。今の会話は終わる）

履歴の元: ~/.claude/history.jsonl（入力した文）と ~/.claude/projects/*/<セッションID>.jsonl（会話記録）
"""
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HOME = os.path.expanduser("~")
HISTORY = os.path.join(HOME, ".claude", "history.jsonl")
HANDOFF_DIR = os.path.join(HOME, ".claude", "tmp", "ct-handoff")
OUT_DIR = os.path.join(HOME, ".claude", "tmp", "history-handoff")
SELF = os.path.abspath(__file__)
HUB = os.path.join(HOME, "www", "ticket_v2_hub")
# 参照だけの /ct-redmine 番号（comment: など書き込みの形は対象外）。hub が補足を後ろに付けて送る形も含む
REDMINE_VIEW = re.compile(r"^\s*/ct-redmine\s+#?(\d{4,6})(?!\S)(?!\s+(?:comment|status|assign|attach)\s*:)")
MAX_LIST = 5


def find(ticket, exclude=""):
    """番号が出てくる過去のセッション（新しい順）。hub の会話と /na- の指示は数えない（作業の会話ではないため）"""
    pat = re.compile(rf"(?<!\d){ticket}(?!\d)")
    sess = {}
    try:
        with open(HISTORY, encoding="utf-8") as f:
            for line in f:
                if ticket not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                text, sid, proj = d.get("display") or "", d.get("sessionId") or "", d.get("project") or ""
                if not sid or sid == exclude or not pat.search(text) or proj == HUB or text.lstrip().startswith("/na-"):
                    continue
                s = sess.setdefault(sid, {"session": sid, "project": proj, "first": d.get("timestamp", 0), "count": 0, "prompts": []})
                s["last"] = d.get("timestamp", 0)
                s["count"] += 1
                s["prompts"].append(re.sub(r"\s+", " ", text)[:70])
    except OSError:
        return []
    out = []
    for s in sess.values():
        tr = glob.glob(os.path.join(HOME, ".claude", "projects", "*", s["session"] + ".jsonl"))
        if not tr:
            continue  # 会話記録が消えている（開き直しも書き出しもできない）
        s["transcript"] = tr[0]
        s["updated"] = os.path.getmtime(tr[0]) * 1000
        s["skills"] = sorted(set(re.findall(r"/(ct-[a-z0-9-]+)", " ".join(s["prompts"]))))
        out.append(s)
    out.sort(key=lambda s: s["updated"], reverse=True)
    return out


def live_panes():
    """いま tmux の枠で開いているセッション → 枠のタイトル（例 "[7] env2 claude"）。開発ダッシュボードの statusline が書く対応表から"""
    out = subprocess.run(["tmux", "list-panes", "-a", "-F", "#{pane_id}\t#{pane_title}\t#{pane_tty}"],
                         capture_output=True, text=True).stdout
    panes = [l.split("\t") for l in out.splitlines() if l.count("\t") == 2]
    # Claude が動いている枠だけ（対応表は Claude を終えた後も残るので、枠の tty に claude の処理があるかで見る）
    ps = subprocess.run(["ps", "-o", "tty=,comm=", "-A"], capture_output=True, text=True).stdout
    claude_ttys = {l.split()[0] for l in ps.splitlines() if len(l.split()) >= 2 and l.split()[-1].rsplit("/", 1)[-1] == "claude"}
    alive = {pid: title for pid, title, tty in panes if tty.removeprefix("/dev/") in claude_ttys}
    try:  # monitor タブの枠なら [n] で出す（hub の hub_status。無ければ枠のタイトルのまま）
        sys.path.insert(0, os.path.join(HOME, ".local", "share", "ticket-v2", "hub", "bin"))
        import hub_status as hs
        for p in hs.tl.load_panes("monitor"):
            m = hs.SLOT_RE.match(hs.slot_title(p["title"]))
            if m and p["id"] in alive:
                alive[p["id"]] = f"[{m.group(1)}]"
    except (Exception, SystemExit):  # monitor タブが無いセッション（試験用など）では tl.load_panes が sys.exit する（2026-11-25 試験）
        pass
    live = {}
    for f in glob.glob(os.path.join(HOME, ".local", "share", "dev-dashboard", "cache", "pane-*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if d.get("pane") in alive and d.get("session_id"):
            live[d["session_id"]] = alive[d["pane"]] or d["pane"]
    return live


def fmt_time(ms):
    return time.strftime("%m-%d %H:%M", time.localtime(ms / 1000)) if ms else "?"


SENT_DIR = os.path.join(HOME, ".local", "share", "ticket-v2", "hub", "sent")
SENT_TTL = 120


def from_hub(prompt):
    """hub の na_to.py がこの枠へ 2 分以内に同じ文を送った印があれば True（印は1回使ったら消す）"""
    pane = os.environ.get("TMUX_PANE", "")
    path = os.path.join(SENT_DIR, f"pane-{pane.lstrip('%')}.json")
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return False
    norm = lambda t: re.sub(r"\s+", " ", t).strip()
    if time.time() - d.get("at", 0) > SENT_TTL or norm(d.get("text", ""))[:60] != norm(prompt)[:60]:
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    return True


def hook():
    data = json.load(sys.stdin)
    m = REDMINE_VIEW.match(data.get("prompt") or "")
    if not m:
        return
    if not from_hub(data.get("prompt") or ""):
        return  # 枠で直接打った /ct-redmine では聞かない（hub から指示したときだけ。2026-11-25 ユーザー指定）
    n = m.group(1)
    cwd = data.get("cwd") or os.getcwd()
    found = find(n, exclude=data.get("session_id") or "")
    handoff = os.path.join(HANDOFF_DIR, f"{n}_session_handoff.md")
    has_handoff = os.path.exists(handoff)
    if not found and not has_handoff:
        return
    live = live_panes()
    lines = [f"[ticket_sessions] #{n} が出てくる過去のセッションが {len(found)} 件あります（新しい順。最大 {MAX_LIST} 件）。"]
    for k, s in enumerate(found[:MAX_LIST], 1):
        same = ("この枠と同じ workspace" if os.path.realpath(s["project"]) == os.path.realpath(cwd)
                else f"別の workspace（{s['project']}）")
        if s["session"] in live:
            same += f"・いま別の枠（{live[s['session']]}）で開いている（開き直し不可）"
        lines.append(f"{k}. session={s['session']} 最終 {fmt_time(s['updated'])}・{same}・#{n} を含む入力 {s['count']} 件"
                     + (f"・スキル {' '.join(s['skills'])}" if s["skills"] else "") + f"・最後の入力「{s['prompts'][-1]}」")
    if has_handoff:
        lines.append(f"ct-handoff の引き継ぎファイルもあります: {handoff}（最終更新 {fmt_time(os.path.getmtime(handoff) * 1000)}）")
    lines += [
        "",
        "Redmine を読み込む前に（ct-redmine の手順を始める前に）、AskUserQuestion で1回だけ次を聞くこと。選択肢は見つかったものだけ出す:",
        f"- 「前回のセッションを開き直す」: この枠と同じ workspace で、いま別の枠で開いていないセッションだけ。選ばれたら `python3 {SELF} resume <session>` を実行して終わる（この会話は終了し、同じ枠で前回の会話が開く）",
        f"- 「前回の会話を読み込んでから続ける」: `python3 {SELF} handoff <session>` で直近の会話を書き出し、出たパスを Read してから ct-redmine を進める（別の workspace のセッションでも可）",
        "- 「引き継ぎファイルを読んでから続ける」: 引き継ぎファイルがあるときだけ。Read してから ct-redmine を進める",
        "- 「使わずに新しく読む」: そのまま ct-redmine を進める",
        "どのセッションかは、件数が複数なら質問の選択肢の説明に最終日時と最後の入力を書いて選べるようにする。",
    ]
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(lines)}}, ensure_ascii=False))


def transcript_of(sid):
    tr = glob.glob(os.path.join(HOME, ".claude", "projects", "*", sid + ".jsonl"))
    if not tr:
        sys.exit(f"セッション {sid} の会話記録が見つかりません")
    return tr[0]


def handoff(sid, turns=10):
    """bin/claude-history の ctrl-t と同じ形: 直近 turns 往復の、発言と返答の本文だけ（ツールの出力・思考は除く）"""
    msgs, project = [], ""
    with open(transcript_of(sid), encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain") or d.get("isMeta") or d.get("isCompactSummary"):
                continue
            project = d.get("cwd") or project
            c = (d.get("message") or {}).get("content")
            if d.get("type") == "user" and isinstance(c, str):
                t = re.sub(r"(?s)<system-reminder>.*?</system-reminder>", "", c).strip()
                if t and not re.match(r"^<(command-|local-command-)", t):
                    msgs.append(("user", d.get("timestamp", ""), t))
            elif d.get("type") == "assistant" and isinstance(c, list):
                t = "\n".join(x.get("text", "") for x in c if x.get("type") == "text").strip()
                if t:
                    msgs.append(("assistant", d.get("timestamp", ""), t))
    users = [k for k, m in enumerate(msgs) if m[0] == "user"]
    start = users[-turns] if len(users) > turns else 0
    recent = msgs[start:]
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{time.strftime('%Y%m%d-%H%M%S')}_claude_{sid}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 別セッションの直近の会話（Claude）\n\n- セッション: {sid}\n- 作業ディレクトリ: {project or '-'}\n"
                f"- 範囲: 直近 {sum(1 for m in recent if m[0] == 'user')} 往復（全 {len(users)} 往復のうち）\n"
                "- 含むもの: 発言と返答の本文だけ。ツールの実行結果・ファイルの中身・思考は含まない\n\n---\n\n")
        for role, ts, text in recent:
            try:
                ts = time.strftime("%m-%d %H:%M", time.localtime(time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone))
            except ValueError:
                pass
            f.write(f"## {'あなた' if role == 'user' else 'Claude'}（{ts}）\n\n{text}\n\n")
    print(path)


def resume(sid):
    """今の tmux の枠で開き直す。起動していた bin/claude の引数（リポジトリ名・--permission-mode など）を引き継ぐ"""
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        sys.exit("tmux の中ではないので開き直せません。`claude --resume " + sid + "` を手で実行してください")
    tr = transcript_of(sid)
    project = ""
    with open(tr, encoding="utf-8") as f:
        for line in f:
            if '"cwd"' in line:
                try:
                    project = json.loads(line).get("cwd") or ""
                except ValueError:
                    continue
                if project:
                    break
    here = subprocess.run(["tmux", "display", "-p", "-t", pane, "#{pane_current_path}"], capture_output=True, text=True).stdout.strip()
    if project and os.path.realpath(here) != os.path.realpath(project):
        # 枠と環境の対応（[1]〜[4]=環境1 など）が崩れるので、別の workspace のセッションは開き直さない（handoff で読む）
        sys.exit(f"⛔ 開き直しません: セッションの workspace（{project}）がこの枠（{here}）と違います。handoff で会話を読んでください")
    if sid in live_panes():
        sys.exit(f"⛔ 開き直しません: このセッションはいま別の枠（{live_panes()[sid]}）で開いています")
    tty = subprocess.run(["tmux", "display", "-p", "-t", pane, "#{pane_tty}"], capture_output=True, text=True).stdout.strip()
    ps = subprocess.run(["ps", "-o", "args=", "-t", tty.removeprefix("/dev/")], capture_output=True, text=True).stdout
    cmd = None
    for line in ps.splitlines():
        a = line.split()
        if len(a) >= 2 and re.search(r"(^|/)(ba|z)?sh$", a[0]) and re.search(r"(^|/)bin/claude$", a[1]):
            kept, i = [], 2
            while i < len(a):
                if a[i] in ("-c", "--continue"):
                    pass
                elif a[i] in ("-r", "--resume"):
                    i += 1
                elif not a[i].startswith("--resume="):
                    kept.append(a[i])
                i += 1
            cmd = " ".join(["bin/claude", *map(shlex.quote, kept), "--resume", shlex.quote(sid)])
            break
    if not cmd:
        repos = [r for r in ("ticket_v2", "ticket_v2_api") if os.path.isdir(os.path.join(project, r))]
        cmd = (" ".join(["bin/claude", *repos, "--resume", shlex.quote(sid)]) if os.access(os.path.join(project, "bin/claude"), os.X_OK)
               else f"claude --resume {shlex.quote(sid)}")
    if os.environ.get("TICKET_SESSIONS_DRY"):  # 試験用: 切り替えずにコマンドだけ出す
        print(f"[dry] {pane} を開き直すコマンド: {cmd}（{project}）")
        return
    # 自分の枠を置き換えるので、この返事が画面に出てから切り替える
    shell = os.environ.get("SHELL", "/bin/zsh")
    subprocess.Popen(["sh", "-c", f"sleep 2; tmux respawn-pane -k -t {shlex.quote(pane)} -c {shlex.quote(project or HOME)} "
                      + shlex.quote(f"{cmd}; exec {shell} -l")], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"2 秒後にこの枠（{pane}）で開き直します: {cmd}（{project}）")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--hook"]:
        try:
            hook()
        except (Exception, SystemExit) as e:  # hook の失敗でプロンプトを止めない（下の部品の sys.exit も受ける）
            print(f"ticket_sessions hook: {type(e).__name__}: {e}", file=sys.stderr)
    elif a[:1] == ["find"] and len(a) >= 2:
        ex = a[a.index("--exclude") + 1] if "--exclude" in a else ""
        for s in find(a[1].lstrip("#"), ex):
            print(f"{s['session']}  {fmt_time(s['updated'])}  {s['project']}  {s['count']}件  {s['prompts'][-1]}")
    elif a[:1] == ["handoff"] and len(a) >= 2:
        handoff(a[1], int(a[2]) if len(a) > 2 else 10)
    elif a[:1] == ["resume"] and len(a) >= 2:
        resume(a[1])
    else:
        print(__doc__)
