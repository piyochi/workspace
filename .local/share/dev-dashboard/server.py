#!/usr/bin/env python3
"""開発ダッシュボード（自宅 LAN 向けの小さな Web サーバー）。

  GET  /             … index.html
  GET  /api/status   … 環境1・2のサーバー状態 + Claude / Codex の使用率
  POST /api/run      … ~/bin/local-server <up|down|restart> <env> <comp> を裏で実行
  GET  /api/pane     … [n] の枠の画面の文字と、起動できるモード
  GET  /api/links    … AI（Claude / Codex）が出した文章の URL（直近7日・新しい順。cat=種類・q=フリーワード）
  GET  /api/redmine  … 自分担当の未完了チケット（5分キャッシュ、refresh=1 で取り直し）と、各チケットの枠・ブランチ・issue docs
  GET  /api/history  … 1 チケットを全期間で探す（Claude・Codex の記録全部と各環境の git のコミット）
  POST /api/link     … [n] の枠の連動先（@link_slot。「2,4」のように複数可）を付ける・外す
  POST /api/cli      … [n] の枠で Claude / Codex を起動（monitor.txt のコマンド）・停止（入力待ちのときだけ）
  GET  /api/job      … 実行中・直近の操作の出力

守り:
  - config.json の allow_ips にある接続元しか受け付けない（"*" なら制限なし。はじいた IP は server.log に出す）
  - 合言葉（config.json の key）が要る。最初に /?key=<合言葉> で開くと cookie に入り、以降は不要
  - POST は X-Dashboard ヘッダーも要る（別サイトからのフォーム送信対策）
設定は config.json（無ければ既定値）。
"""
import glob
import hmac
import json
import sys
from urllib.parse import parse_qs, urlsplit
import os
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "cache")
HOME = os.path.expanduser("~")
LOCAL_SERVER = os.path.join(HOME, "bin", "local-server")

DEFAULT_CONFIG = {
    "port": 8765,
    "bind": "0.0.0.0",
    "allow_ips": ["127.0.0.1", "::1"],
    "key": "",
    # Codex のアカウント = CODEX_HOME。増えたらここに足す（label は表示名）
    "codex_homes": [{"path": "~/.codex", "label": "codex"}],
    # Claude は statusline.py が cache/claude-*.json に書いたものを全部表示する。
    # この時間より古い cache は「古い」と表示する
    "stale_minutes": 30,
}

ENVS = ("env1", "env2")
COMPS = ("api", "app", "sqs", "all")
ACTIONS = {"up": "起動", "down": "停止", "restart": "再起動"}
STATUS_LINE = re.compile(r"^([●○])\s+(env\d)\s+(api|app|sqs)")

job_lock = threading.Lock()
job = {"running": False, "target": None, "output": "", "rc": None, "started": None, "finished": None}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(os.path.join(BASE, "config.json")) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def server_status():
    try:
        out = subprocess.run([LOCAL_SERVER, "status"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": str(e)}
    envs = {e: {} for e in ENVS}
    other = []
    for line in out.splitlines():
        m = STATUS_LINE.match(line.strip())
        if m:
            envs.setdefault(m.group(2), {})[m.group(3)] = m.group(1) == "●"
        elif line.strip():
            other.append(line.strip())
    return {"envs": envs, "messages": other}


def window(w):
    """各 CLI の窓の形をそろえる: {percent, resets_at(epoch秒)}。"""
    if not isinstance(w, dict):
        return None
    p = next((w[k] for k in ("used_percentage", "used_percent", "utilization") if isinstance(w.get(k), (int, float))), None)
    if p is None:
        return None
    r = w.get("resets_at")
    if isinstance(r, str):
        try:
            from datetime import datetime
            r = datetime.fromisoformat(r.replace("Z", "+00:00")).timestamp()
        except ValueError:
            r = None
    elif isinstance(w.get("resets_in_seconds"), (int, float)):
        r = None  # 基準時刻が不明なので使わない
    return {"percent": float(p), "resets_at": r}


def claude_usage():
    rows = []
    for path in sorted(glob.glob(os.path.join(CACHE, "claude-*.json"))):
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        rl = d.get("rate_limits") or {}
        rows.append({
            "label": d.get("label") or "claude",
            "updated_at": d.get("updated_at"),
            "windows": {
                "5h": window(rl.get("five_hour")),
                "週": window(rl.get("seven_day")),
            },
        })
    return rows


def tail_lines(path, size=512 * 1024):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        f.seek(max(0, end - size))
        return f.read().decode("utf-8", "replace").splitlines()


def find_rate_limits(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("rate_limits"), dict):
            return obj["rate_limits"]
        for v in obj.values():
            r = find_rate_limits(v)
            if r:
                return r
    return None


def codex_usage(cfg):
    rows = []
    for acct in cfg["codex_homes"]:
        home = os.path.expanduser(acct["path"])
        files = sorted(glob.glob(os.path.join(home, "sessions", "*", "*", "*", "*.jsonl")), key=os.path.getmtime, reverse=True)
        row = {"label": acct.get("label") or os.path.basename(home), "updated_at": None, "windows": {}, "plan": None}
        for path in files[:5]:
            try:
                lines = tail_lines(path)
            except OSError:
                continue
            for line in reversed(lines):
                if '"rate_limits"' not in line:
                    continue
                try:
                    rl = find_rate_limits(json.loads(line))
                except ValueError:
                    continue
                if not rl:
                    continue
                for key in ("primary", "secondary"):
                    w = rl.get(key)
                    if not isinstance(w, dict):
                        continue
                    mins = w.get("window_minutes") or 0
                    name = "5h" if mins and mins <= 300 else "週" if mins >= 10080 else f"{mins}分"
                    row["windows"][name] = window(w)
                row["plan"] = rl.get("plan_type")
                row["updated_at"] = os.path.getmtime(path)
                break
            if row["updated_at"]:
                break
        rows.append(row)
    return rows


TMUX_SESSION = "ticket_v2_project"
SLOT_TITLE = re.compile(r"\[(\d+)\]\s+(\S+)\s+(claude|codex)(?:\(([^)]*)\))?")
CODEX_WAIT = re.compile(r"Would you like to (run the following command|make the following edits|grant these permissions)\?")
SHELLS = {"zsh", "bash", "sh", "fish"}


def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=5)


def codex_state(pane_id):
    """画面の下 15 行から Codex の状態を読む（~/bin/tmux-codex-busy と同じ判定）。"""
    screen = [l for l in tmux("capture-pane", "-p", "-t", pane_id).stdout.splitlines() if l.strip()][-15:]
    text = "\n".join(screen)
    if CODEX_WAIT.search(text):
        return "wait"
    if "Working (" in text:
        return "busy"
    return "idle"


TICKET = re.compile(r"(?<!\d)(\d{5})(?!\d)")


SCREEN_TICKET = re.compile(r"#(\d{5})(?!\d)")
PROMPT_TICKET = re.compile(r"(?<![\d.])#?(1\d{4})(?!\d)")
transcript_cache = {}  # transcript_path -> {"offset", "counts"}（追記分だけ読む）


def screen_ticket(pane_id):
    """Codex 用: 枠の画面（直近 300 行）に出ている「#番号」のうち一番多いもの。無ければ ""。"""
    text = tmux("capture-pane", "-p", "-J", "-S", "-300", "-t", pane_id).stdout
    counts = {}
    for n in SCREEN_TICKET.findall(text):
        counts[n] = counts.get(n, 0) + 1
    return max(counts, key=counts.get) if counts else ""


def prompt_text(entry):
    """transcript の1行から、ユーザーが入力した文だけを取り出す（ツールの結果・システムの差し込みは除く）。"""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return ""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    if not isinstance(content, str):
        return ""
    if content.lstrip().startswith("<"):
        # /ct-redmine 14747 のようなスラッシュコマンドは <command-args> に入力が入る。それ以外の差し込みは除く
        m = re.search(r"<command-args>(.*?)</command-args>", content, re.S)
        return m.group(1) if m and "<command-name>" in content else ""
    return content


SKILL_CMD = re.compile(r"<command-name>/([\w:.-]+)</command-name>")
SKILL_MD = re.compile(r"skills/([a-z0-9][a-z0-9-]*)/SKILL\.md")


def known_skills():
    """スキル名の一覧（ホーム・各環境のプロジェクト）。/exit などの組み込みコマンドをスキルと見なさないために使う。"""
    names = set()
    for d in [os.path.join(HOME, ".claude", "skills")] + glob.glob(os.path.join(HOME, "www", "ticket_v2*", ".claude", "skills")):
        try:
            names.update(n for n in os.listdir(d) if not n.startswith("."))
        except OSError:
            pass
    return names


def read_new_lines(path, st):
    """前回読んだ所から後ろの、改行で終わっている行だけを返す（ファイルが縮んでいたら最初から）。"""
    size = os.path.getsize(path)
    if size < st["offset"]:
        st.clear()
        st["offset"] = 0
    if size <= st.get("offset", 0):
        return []
    with open(path, "rb") as f:
        f.seek(st["offset"])
        chunk = f.read()
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return []
    st["offset"] += last_nl + 1
    return chunk[:last_nl].decode("utf-8", "replace").splitlines()


def claude_session_info(pane_id):
    """Claude 用: その枠のセッションの (チケット番号, 最後に使った ct- のスキル)。

    チケット番号はユーザーが入力した文に出てくる番号のうち一番多いもの。スキルは Skill ツールの呼び出しか
    /<スキル名> の入力のうち最後のもの。枠とセッションの対応は statusline.py が cache/pane-<id>.json に書く。
    /clear すると新しいセッションになるので、どちらも消える。
    画面やブランチは使わない（画面は話題に出ただけの番号を拾い、ブランチは環境で1つなので新しいセッションにも付く）。
    """
    try:
        with open(os.path.join(CACHE, f"pane-{pane_id.lstrip('%')}.json")) as f:
            path = json.load(f)["transcript_path"]
        st = transcript_cache.setdefault(path, {"offset": 0})
        lines = read_new_lines(path, st)
    except (OSError, ValueError, KeyError):
        return "", ""
    counts = st.setdefault("counts", {})
    skills = None
    for line in lines:
        if '"user"' in line:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            text = prompt_text(entry)
            for n in PROMPT_TICKET.findall(text):
                counts[n] = counts.get(n, 0) + 1
            if "<command-name>" in line:
                skills = skills or known_skills()
                for name in SKILL_CMD.findall(json.dumps(entry.get("message", {}), ensure_ascii=False)):
                    if name.startswith("ct-") and name in skills:
                        st["skill"] = name
        if '"name":"Skill"' in line:
            m = re.search(r'"name":"Skill","input":\{"skill":"([^"]+)"', line)
            if m and m.group(1).startswith("ct-"):
                st["skill"] = m.group(1)
    return (max(counts, key=counts.get) if counts else ""), st.get("skill", "")


codex_rollouts = {}  # codex の pid -> 記録ファイル（lsof は重いので pid ごとに1回）


def codex_skill(tty, kinds_pids):
    """Codex 用: 動いている Codex の記録ファイルから、最後に SKILL.md を読んだスキル名。取れなければ ""。

    Codex にはスキルを使った記録がはっきり残らないので、コマンド実行（exec）で skills/<名前>/SKILL.md を
    読んだものをスキルを使ったと見なす（推測）。
    """
    pid = kinds_pids.get(tty, {}).get("codex")
    if not pid:
        return ""
    if pid not in codex_rollouts:
        try:
            out = subprocess.run(["lsof", "-p", pid, "-Fn"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        paths = [l[1:] for l in out.splitlines() if l.startswith("n") and "/rollout-" in l and l.endswith(".jsonl")]
        codex_rollouts[pid] = max(paths, key=os.path.getmtime) if paths else ""
    path = codex_rollouts[pid]
    if not path:
        return ""
    st = transcript_cache.setdefault(path, {"offset": 0})
    try:
        lines = read_new_lines(path, st)
    except OSError:
        return st.get("skill", "")
    for line in lines:
        if "SKILL.md" not in line or '"response_item"' not in line:
            continue
        try:
            payload = json.loads(line).get("payload", {})
        except ValueError:
            continue
        if payload.get("type") in ("custom_tool_call", "function_call"):
            m = SKILL_MD.search(json.dumps(payload.get("input") or payload.get("arguments") or "", ensure_ascii=False))
            if m and m.group(1).startswith("ct-"):
                st["skill"] = m.group(1)
    return st.get("skill", "")


def running_kinds():
    """端末（tty）ごとに、動いている AI CLI（claude / codex）を返す。ps を1回だけ呼ぶ。

    枠のタイトルは tmuxp で決めた「その枠の既定の CLI」なので、別の CLI を起動した枠もある。実際のプロセスで見る。
    """
    kinds = {}  # tty -> {"claude": pid, "codex": pid}
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,tty=,comm="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return kinds
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        name = os.path.basename(parts[2].strip())
        if name in ("claude", "codex"):
            kinds.setdefault(parts[1], {})[name] = parts[0]
    return kinds


def codex_slots(kinds):
    """Claude のプロセスの環境変数 CODEX_SLOT（起動時に決まる相方の枠番号）。tty -> 番号。"""
    pids = {v["claude"]: tty for tty, v in kinds.items() if "claude" in v}
    if not pids:
        return {}
    try:
        out = subprocess.run(["ps", "eww", "-o", "pid=,command=", "-p", ",".join(pids)],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    slots = {}
    for line in out.splitlines():
        pid = line.split(None, 1)[0] if line.strip() else ""
        m = re.search(r"(?:^|\s)CODEX_SLOT=(\d+)(?:\s|$)", line)
        if pid in pids and m:
            slots[pids[pid]] = m.group(1)
    return slots


def pane_status(pane_id, cmd, ai_state, tty, slot_kind, kinds):
    """(動いている CLI の種類, 状態) を返す。止まっていれば種類は枠の既定。"""
    # CLI はラッパーの bash から起動されるので、ログインシェル（zsh）に戻っていれば止まっている
    if cmd == "zsh":
        return slot_kind, "stopped"
    found = kinds.get(tty.removeprefix("/dev/"), {})
    kind = "codex" if "codex" in found and "claude" not in found else ("claude" if "claude" in found else slot_kind)
    if kind == "claude":
        return kind, (ai_state if ai_state in ("busy", "wait") else "idle")
    return kind, codex_state(pane_id)


def ai_panes():
    """tmuxp（ticket_v2_project）の monitor タブの [1]〜[12]（Claude / Codex）の稼働状態。

    状態: busy 処理中 / wait 許可・回答待ち / idle 入力待ち / stopped CLI が動いていない
    フォーカス中の枠は「★ FOCUS [n] ...」、元の位置は「[n] → left」になるので後者は飛ばす。
    """
    try:
        if tmux("has-session", "-t", TMUX_SESSION).returncode != 0:
            return {"running": False, "slots": []}
        out = tmux("list-panes", "-s", "-t", TMUX_SESSION, "-F",
                   "#{window_name}\t#{pane_id}\t#{pane_current_command}\t#{@ai_state}\t#{@cm_title}\t#{pane_tty}\t#{@link_slot}\t#{pane_title}").stdout
        kinds = running_kinds()
        env_slots = codex_slots(kinds)
    except (OSError, subprocess.TimeoutExpired):
        return {"running": False, "slots": []}
    slots = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 8 or parts[0] != "monitor":
            continue
        _, pane_id, cmd, ai_state, cm_title, tty, link_slot = parts[:7]
        pane_title = "\t".join(parts[7:])
        m = SLOT_TITLE.search(cm_title)
        if not m or "→ left" in cm_title:
            continue
        n, env, slot_kind = int(m.group(1)), m.group(2), m.group(3)
        kind, state = pane_status(pane_id, cmd, ai_state, tty, slot_kind, kinds)
        task = re.sub(r"^[^\w\[(（]+", "", pane_title)
        task = re.sub(r"\s*\|\s*ticket_v2\w*$", "", task).strip()  # Codex は末尾にフォルダ名が付く
        # 作業名の無い枠はホスト名やフォルダ名がタイトルに入るので出さない
        if state == "stopped" or task == "MacBook-Pro.local" or re.fullmatch(r"ticket_v2\w*", task):
            task = ""
        # チケット番号はタイトルを優先し、無ければ Claude は入力した文・Codex は画面の「#番号」から取る
        m = TICKET.search(task)
        skill = ""
        if state == "stopped":
            ticket = ""
        elif kind == "claude":
            ticket, skill = claude_session_info(pane_id)
        else:
            ticket, skill = screen_ticket(pane_id), codex_skill(tty.removeprefix("/dev/"), kinds)
        if m:
            ticket = m.group(1)
        # 連動先: ダッシュボードで付けた印（@link_slot）を優先し、無ければ Claude の起動時の CODEX_SLOT
        link = None
        marked = parse_link_slots(link_slot)
        if marked:
            link = {"slots": marked, "from": "dashboard"}
        elif state != "stopped" and env_slots.get(tty.removeprefix("/dev/")):
            link = {"slots": [int(env_slots[tty.removeprefix("/dev/")])], "from": "codex_slot"}
        slots[n] = {"slot": n, "env": env, "kind": kind, "slot_kind": slot_kind, "state": state, "task": task, "ticket": ticket,
                    "skill": skill, "link": link,
                    "ticket_from": "title" if m else ("session" if ticket else "")}
    return {"running": True, "slots": [slots[k] for k in sorted(slots)]}


MONITOR_TXT = os.path.join(HOME, ".tmuxp", "ticket_v2_project", "monitor.txt")
# 起動のしかた。Claude は --continue、Codex は resume --last で前回の続き
CLI_MODES = {
    "claude": {"new": "", "continue": "--continue"},
    "codex": {"new": "", "resume": "resume --last"},
}
CLI_ALL_FLAGS = re.compile(r"\s+(--continue|resume\s+--last)\b")
cli_lock = threading.Lock()


def slot_pane(n):
    """monitor タブの [n] の枠（フォーカス中なら「★ FOCUS [n]」の方）。無ければ None。"""
    out = tmux("list-panes", "-s", "-t", TMUX_SESSION, "-F",
               "#{window_name}\t#{pane_id}\t#{@cm_title}\t#{pane_current_command}\t#{@ai_state}\t#{pane_tty}").stdout
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 6 or parts[0] != "monitor" or "→ left" in parts[2]:
            continue
        m = SLOT_TITLE.search(parts[2])
        if m and int(m.group(1)) == n:
            kind, state = pane_status(parts[1], parts[3], parts[4], parts[5], m.group(3), running_kinds())
            return {"id": parts[1], "title": parts[2].replace("★ FOCUS ", ""), "kind": kind,
                    "slot_kind": m.group(3), "state": state}
    return None


def monitor_commands():
    """monitor.txt の各行（「フォルダ | コマンド | タイトル」）を枠番号順に返す。先頭の @ は外す。"""
    rows = []
    try:
        with open(MONITOR_TXT) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [x.strip() for x in line.split(" | ")]
                if len(parts) >= 2:
                    rows.append({"dir": os.path.expanduser(parts[0]), "cmd": parts[1].lstrip("@")})
    except OSError:
        pass
    return rows


def launch_command(n, kind, mode):
    """[n] の枠で kind（claude / codex）を mode で起動するコマンド。

    フォルダは [n] の行のもの。コマンドは同じフォルダの行のうち bin/<kind> を使う行から取るので、
    Codex の枠で Claude を（その逆も）起動できる。CODEX_SLOT（相方の Codex の枠番号）は奇数の枠の Claude だけに付ける。
    """
    rows = monitor_commands()
    if not 1 <= n <= len(rows) or mode not in CLI_MODES.get(kind, {}):
        return None
    d = rows[n - 1]["dir"]
    src = next((r["cmd"] for r in rows if r["dir"] == d and f"bin/{kind}" in r["cmd"]), None)
    if not src:
        return None
    base = re.sub(r"^CODEX_SLOT=\d+\s+", "", CLI_ALL_FLAGS.sub("", src))
    if kind == "claude" and n % 2 == 1:
        base = f"CODEX_SLOT={n + 1} {base}"
    extra = CLI_MODES[kind][mode]
    return d, (f"{base} {extra}" if extra else base)


def pane_text(n, lines=100):
    """[n] の枠の画面を文字で返す（スクロールした分も含め直近 lines 行）と、起動できるコマンドの一覧。"""
    try:
        if tmux("has-session", "-t", TMUX_SESSION).returncode != 0:
            return {"error": "ticket_v2_project は動いていません"}
        p = slot_pane(n)
        if not p:
            return {"error": f"[{n}] の枠が見つかりません"}
        text = tmux("capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", p["id"]).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": str(e)}
    labels = {"new": "新規", "continue": "continue", "resume": "resume --last"}
    # 枠の既定の CLI を先に並べる
    order = [p["slot_kind"]] + [k for k in CLI_MODES if k != p["slot_kind"]]
    modes = []
    for k in order:
        for m in CLI_MODES[k]:
            lc = launch_command(n, k, m)
            if lc:
                modes.append({"kind": k, "mode": m, "label": f"{'Claude' if k == 'claude' else 'Codex'} {labels[m]}", "cmd": lc[1]})
    return {"slot": n, "title": p["title"], "kind": p["kind"], "slot_kind": p["slot_kind"], "state": p["state"],
            "modes": modes, "text": text.rstrip("\n")}


def parse_link_slots(value):
    """印 @link_slot（「2,4」）を枠番号のリストにする。"""
    return sorted({int(x) for x in str(value).split(",") if x.strip().isdigit()})


def set_link(n, targets):
    """[n] の枠に連動先の印（tmux のペインオプション @link_slot、「2,4」のように複数可）を付ける。空なら外す。

    印はペインに付くので、フォーカス切り替えで枠の位置が動いても付いて回る。
    ct-link スキル（~/.claude/skills/ct-link）の link_target.py がこの印を CODEX_SLOT より先に見る。
    """
    p = slot_pane(n)
    if not p:
        return {"error": f"[{n}] の枠が見つかりません"}, 404
    if not targets:
        tmux("set-option", "-p", "-u", "-t", p["id"], "@link_slot")
        return {"ok": True, "message": f"[{n}] の連動先を外しました（起動時の CODEX_SLOT があればそれに戻ります）"}, 200
    tmux("set-option", "-p", "-t", p["id"], "@link_slot", ",".join(map(str, targets)))
    return {"ok": True, "message": f"[{n}] の連動先を {''.join(f'[{t}]' for t in targets)} にしました"}, 200


def wait_cmd(pane_id, want_shell, timeout):
    """ペインがシェルに戻る（want_shell=True）/ シェルから CLI に変わる（False）まで待つ。"""
    end = time.time() + timeout
    while time.time() < end:
        cur = tmux("display", "-p", "-t", pane_id, "#{pane_current_command}").stdout.strip()
        if (cur == "zsh") == want_shell:
            return True
        time.sleep(0.5)
    return False


def cli_launch(n, kind, mode):
    """[n] の枠で kind（claude / codex）を起動する。シェル（zsh）に戻っている枠だけ。"""
    p = slot_pane(n)
    if not p:
        return {"error": f"[{n}] の枠が見つかりません"}, 404
    if mode not in CLI_MODES.get(kind, {}):
        return {"error": f"{kind} に {mode} はありません"}, 400
    if p["state"] != "stopped":
        return {"error": f"{p['title']} はもう動いています"}, 409
    lc = launch_command(n, kind, mode)
    if not lc:
        return {"error": "monitor.txt に起動コマンドが見つかりません"}, 404
    d, cmd = lc
    tmux("send-keys", "-t", p["id"], f"cd '{d}' && {cmd}", "Enter")
    ok = wait_cmd(p["id"], want_shell=False, timeout=15)
    return {"ok": ok, "message": f"{cmd} を送りました" + ("" if ok else "（15秒以内に起動を確認できませんでした）")}, 200


def cli_stop(n):
    """[n] の枠の Claude / Codex を終了する。入力待ちのときだけ（処理中・確認待ちは中断になるので止めない）。

    Ctrl+C は「もう1回押すと終了」の表示が出ている短い間に2回目を押さないと終了しない（Claude / Codex とも）。
    入力欄に文字があると1回目は文字を消すだけなので、「間をあけずに2回」をシェルに戻るまで最大3組送る。
    """
    p = slot_pane(n)
    if not p:
        return {"error": f"[{n}] の枠が見つかりません"}, 404
    if p["state"] == "stopped":
        return {"error": f"{p['title']} は動いていません"}, 409
    if p["state"] != "idle":
        return {"error": f"{p['title']} は処理中か確認待ちです。終わってから停止してください"}, 409
    for _ in range(3):
        tmux("send-keys", "-t", p["id"], "C-c")
        time.sleep(0.3)
        tmux("send-keys", "-t", p["id"], "C-c")
        if wait_cmd(p["id"], want_shell=True, timeout=3):
            return {"ok": True, "message": "停止しました"}, 200
    return {"ok": False, "message": "停止を確認できませんでした。画面を見てください"}, 200


LINK_URL = re.compile(r"https?://[^\s<>()\[\]{}\"'`|*、。，）」』]+")  # * は Markdown の太字なので URL に含めない
LINK_DAYS = 7
ENV_DIRS = {"ticket_v2": "env1", "ticket_v2_second": "env2", "ticket_v2_third": "env3", "ticket_v2_fourth": "env4"}
links_lock = threading.Lock()
links = {}          # url -> {url, ts, cat, src, path, context}
links_scan_lock = threading.Lock()  # 集める処理を同時に2つ走らせない（読み進めた位置が狂う）
links_files = {}    # 記録ファイル -> {"offset", "cwd"}（追記分だけ読む）


def link_category(url):
    """URL の種類（セレクトの選択肢）。"""
    host = urlsplit(url).hostname or ""
    if host == "github.com" or host.endswith(".github.com") or host.endswith("githubusercontent.com"):
        return "GitHub"
    if host == "claude.ai" and "/artifact" in url:
        return "アーティファクト"
    if host.endswith("claude.ai") or host.endswith("claude.com") or host.endswith("anthropic.com"):
        return "Claude"
    if "redmine" in host:
        return "Redmine"
    if host in ("localhost", "127.0.0.1") or "corichlocal" in host or host.startswith("192.168."):
        return "ローカル"
    if host.endswith("corich.tw") or host.endswith("corich.mobi"):
        return "staging"
    if host.endswith("corich.asia"):
        return "testing"
    if host.endswith("corich.me") or host.endswith("corich.co") or host.endswith("corich.jp"):
        return "本番"
    if host.endswith("google.com"):
        return "Google"
    return "その他"


def env_of(cwd):
    """作業フォルダから環境名（env1〜env4）。わからなければフォルダ名。"""
    for part in reversed(os.path.normpath(cwd or "").split(os.sep)):
        if part in ENV_DIRS:
            return ENV_DIRS[part]
    return os.path.basename(cwd or "") or "?"


LINE_TICKET = re.compile(r"#(1\d{4})(?!\d)|/issues/(1\d{4})(?!\d)")


def main_ticket(text):
    """ユーザーの入力に出たチケット番号のうち、いちばん多く出たもの（同数なら先に出たもの）。無ければ ""。

    圧縮後の要約や貼り付けには番号がいくつも出るので、最後の番号ではなく主な番号を取る。
    """
    nums = PROMPT_TICKET.findall(text or "")
    return max(nums, key=lambda n: (nums.count(n), -nums.index(n))) if nums else ""


def add_links(text, ts, src, path, ticket=""):
    """ticket: そのセッションでユーザーが最後に入力したチケット番号。URL の行に #番号・Redmine の URL があればそちらを優先する。"""
    for raw in LINK_URL.findall(text or ""):
        url = raw.rstrip(".,;:!?*_~>")
        host = urlsplit(url).hostname or ""
        # 「https://x」「https://…」のような書きかけや、説明用の伏せ字（…・xxxx）は拾わない
        if not host or ("." not in host and host != "localhost") or "…" in url or re.search(r"x{4,}", url, re.I):
            continue
        # その URL が書かれていた行。URL は切らずに残し、前後を最大 60 文字ずつにする（画面で URL 部分をリンクにする）
        line = next((l for l in text.splitlines() if raw in l), "")
        i = line.find(raw)
        # raw の末尾から外した文字（Markdown の太字の ** など）は、後ろの文と一緒に記号を消す
        before, after = line[:i], raw[len(url):] + line[i + len(raw):]
        clean = lambda t: re.sub(r"\s+", " ", re.sub(r"[*`#>|]+", " ", t))
        before, after = clean(before).lstrip(), clean(after).rstrip()
        before = ("…" + before[-60:]) if len(before) > 60 else before
        after = (after[:60] + "…") if len(after) > 60 else after
        ctx = before + url + after
        m = LINE_TICKET.search(line)
        tk = (m.group(1) or m.group(2)) if m else ticket
        cur = links.get(url)
        if cur is None or ts < cur["ts"]:
            links[url] = {"url": url, "ts": ts, "cat": link_category(url), "src": src, "path": path, "context": ctx, "ticket": tk or ""}


def iso_ts(value):
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def scan_links_once():
    """Claude・Codex の記録（直近 LINK_DAYS 日に更新されたもの）から、AI が出した文章の URL を集める。

    ユーザーの入力・道具の結果は見ない。同じ URL は初めて出た時刻で1件にまとめる。
    """
    limit = time.time() - LINK_DAYS * 86400
    files = [(f, "claude") for f in glob.glob(os.path.join(HOME, ".claude", "projects", "*", "*.jsonl"))]
    files += [(f, "codex") for f in glob.glob(os.path.join(HOME, ".codex", "sessions", "*", "*", "*", "*.jsonl"))]
    for path, kind in files:
        try:
            if os.path.getmtime(path) < limit:
                continue
            st = links_files.setdefault(path, {"offset": 0, "cwd": ""})
            lines = read_new_lines(path, st)
        except OSError:
            continue
        for line in lines:
            if kind == "claude":
                if '"type":"assistant"' not in line and '"cwd"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                st["cwd"] = d.get("cwd") or st.get("cwd", "")
                tk = main_ticket(prompt_text(d))
                if tk:
                    st["ticket"] = tk  # このあとに出た URL は、このチケットの作業で出たものとみなす
                if d.get("type") != "assistant" or "http" not in line:
                    continue
                text = "\n".join(b.get("text", "") for b in (d.get("message") or {}).get("content") or []
                                 if isinstance(b, dict) and b.get("type") == "text")
            else:
                if '"session_meta"' in line:
                    try:
                        st["cwd"] = json.loads(line).get("payload", {}).get("cwd", "")
                    except ValueError:
                        pass
                    continue
                if '"user"' in line:
                    try:
                        tk = main_ticket(codex_prompt_text(json.loads(line).get("payload") or {}))
                    except ValueError:
                        tk = ""
                    if tk:
                        st["ticket"] = tk
                    continue
                if '"assistant"' not in line or "http" not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                pl = d.get("payload") or {}
                if pl.get("type") != "message" or pl.get("role") != "assistant":
                    continue
                text = "\n".join(c.get("text", "") for c in pl.get("content") or [] if isinstance(c, dict))
            with links_lock:
                add_links(text, iso_ts(d.get("timestamp")) or os.path.getmtime(path),
                          f"{env_of(st.get('cwd'))} {kind}", path, st.get("ticket", ""))
    with links_lock:
        for url in [u for u, v in links.items() if v["ts"] < limit]:
            del links[url]


def scan_links_locked():
    with links_scan_lock:
        scan_links_once()


def links_loop():
    """30秒ごとに集める（枠の返答が終わったとき・「取り直す」は /api/links?rescan=1 でその場で集める）。"""
    while True:
        try:
            scan_links_locked()
        except Exception as e:  # 集め損ねても次の回でやり直す
            print(f"{time.strftime('%F %T')} リンクの収集に失敗: {e}", file=sys.stderr, flush=True)
        time.sleep(30)


def slot_by_path():
    """記録ファイル -> 今それを動かしている枠のタイトル（[n] env kind）。"""
    out = {}
    try:
        panes = tmux("list-panes", "-s", "-t", TMUX_SESSION, "-F", "#{window_name}\t#{pane_id}\t#{pane_tty}\t#{@cm_title}").stdout
    except (OSError, subprocess.TimeoutExpired):
        return out
    kinds = running_kinds()
    for line in panes.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or parts[0] != "monitor" or "→ left" in parts[3]:
            continue
        m = SLOT_TITLE.search(parts[3])
        if not m:
            continue
        label = f"[{m.group(1)}] {m.group(2)}"
        try:
            with open(os.path.join(CACHE, f"pane-{parts[1].lstrip('%')}.json")) as f:
                out[json.load(f)["transcript_path"]] = f"{label} claude"
        except (OSError, ValueError, KeyError):
            pass
        pid = kinds.get(parts[2].removeprefix("/dev/"), {}).get("codex")
        if pid and codex_rollouts.get(pid):
            out[codex_rollouts[pid]] = f"{label} codex"
    return out


def links_query(cat, q, offset, limit):
    with links_lock:
        items = sorted(links.values(), key=lambda v: v["ts"], reverse=True)
    cats = {}
    for v in items:
        cats[v["cat"]] = cats.get(v["cat"], 0) + 1
    if cat:
        items = [v for v in items if v["cat"] == cat]
    if q:
        words = q.lower().split()
        items = [v for v in items if all(w in f"{v['url']} {v['context']} {v['src']} #{v.get('ticket', '')}".lower() for w in words)]
    slots = slot_by_path()
    host = redmine_creds()[0]
    page = [{"url": v["url"], "ts": v["ts"], "cat": v["cat"], "context": v["context"], "ticket": v.get("ticket", ""),
             "ticket_url": f"{host}/issues/{v['ticket']}" if host and v.get("ticket") else "",
             "src": slots.get(v["path"], v["src"])} for v in items[offset:offset + limit]]
    return {"total": len(items), "items": page, "cats": sorted(cats.items(), key=lambda kv: -kv[1]), "days": LINK_DAYS}


# 「#14339 リリース後」「#14339 待ち」「#14339 のマージ後」など、他のチケットを待っている書き方
# 「後」「以降」は動作の言葉が付いたときだけ（表の見出しの「#14399 前 / 後」などを拾わないため）
# 「#13868 リリースまで開発はしない」「#14339 と作業が被るため、…マージされるまで待つ」のように、番号のあとの同じ文で「待つ」ものも拾う
WAIT_TEXT = re.compile(r"#(\d{4,6})\s*(?:の|が)?\s*((?:対応|修正|リリース|マージ|完了|反映|デプロイ|解決)\s*(?:待ち|後|以降|まで)|待ち)"
                       r"|#(\d{4,6})([^#。\n]{0,40}?(?:待つ|待ち(?!ません)))")
WAIT_WORD = re.compile(r"リリース|マージ|対応|完了|反映|デプロイ|解決")
journals_cache = {}  # チケット番号 -> {"updated_on", "notes"}（更新されたチケットだけ取り直す）


def journal_notes(get_one, issue_id, updated_on):
    """チケットのコメント（journals の notes）。更新日時が変わっていなければ前回の結果を使う。"""
    c = journals_cache.get(issue_id)
    if c and c["updated_on"] == updated_on:
        return c["notes"]
    try:
        notes = [j.get("notes") or "" for j in get_one(issue_id).get("journals") or [] if j.get("notes")]
    except Exception:
        return c["notes"] if c else []
    journals_cache[issue_id] = {"updated_on": updated_on, "notes": notes}
    return notes


REDMINE_PROJECT_ID = 133  # tools/claude-corich/bin/redmine.sh の list と同じ（CoRichチケット！）
REDMINE_OPEN = ("新規登録", "進行中", "フィードバック", "ﾌｨｰﾄﾞﾊﾞｯｸ")
redmine_cache = {"at": 0, "data": None}
REPO_NAMES = ("ticket_v2_api", "ticket_v2")


def redmine_creds():
    """Redmine の接続先と API キー。launchd には ~/.zshrc の環境変数が渡らないので、export の行を読む（別ファイルに写さない）。"""
    vals = {k: os.environ.get(k, "") for k in ("REDMINE_HOST", "REDMINE_API_KEY")}
    if not all(vals.values()):
        try:
            with open(os.path.join(HOME, ".zshrc")) as f:
                for line in f:
                    m = re.match(r"\s*export\s+(REDMINE_HOST|REDMINE_API_KEY)=(.*)$", line)
                    if m and not vals[m.group(1)]:
                        vals[m.group(1)] = m.group(2).strip().strip("'\"")
        except OSError:
            pass
    return vals["REDMINE_HOST"].rstrip("/"), vals["REDMINE_API_KEY"]


def redmine_issues():
    """自分担当の未完了チケット（redmine.sh list と同じ条件）。5 分だけ覚えておく。"""
    if redmine_cache["data"] is not None and time.time() - redmine_cache["at"] < 300:
        return redmine_cache["data"]
    host, key = redmine_creds()
    if not host or not key:
        return {"error": "REDMINE_HOST / REDMINE_API_KEY が見つかりません（~/.zshrc の export を読んでいます）"}
    import urllib.request
    def get_json(path):
        req = urllib.request.Request(f"{host}{path}", headers={"X-Redmine-API-Key": key})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)

    def get(path):
        return get_json(path).get("issues", [])

    def get_one(issue_id):
        return get_json(f"/issues/{issue_id}.json?include=journals").get("issue", {})
    try:
        issues = get(f"/issues.json?assigned_to_id=me&project_id={REDMINE_PROJECT_ID}&status_id=open"
                     "&sort=priority:desc,updated_on:desc&limit=100&include=relations")
    except Exception as e:
        return {"error": f"Redmine から取れませんでした: {e}"}
    issues = [i for i in issues if (i.get("status") or {}).get("name") in REDMINE_OPEN]
    # 待ち・関連: Redmine の関連（ブロック・先行）と、件名・説明の「#番号 待ち」。相手のチケットの状態も取る
    rels = {}
    for i in issues:
        me, out = i["id"], []
        for r in i.get("relations") or []:
            other = r["issue_id"] if r["issue_to_id"] == me else r["issue_to_id"]
            t = r["relation_type"]
            if t == "blocks" and r["issue_to_id"] == me:
                out.append({"id": other, "kind": "wait", "via": "ブロック"})
            elif t == "precedes" and r["issue_to_id"] == me:
                out.append({"id": other, "kind": "wait", "via": "先行"})
            elif t in ("blocked", "follows") and r["issue_id"] == me:
                out.append({"id": other, "kind": "wait", "via": "ブロック" if t == "blocked" else "先行"})
            elif t in ("blocks", "precedes"):
                out.append({"id": other, "kind": "blocking", "via": "ブロック" if t == "blocks" else "先行"})
            else:
                out.append({"id": other, "kind": "relates", "via": "関連"})
        texts = [("本文", f"{i.get('subject', '')}\n{i.get('description') or ''}")]
        texts += [("コメント", j) for j in journal_notes(get_one, i["id"], i.get("updated_on", ""))]
        for via, text in texts:
            for m in WAIT_TEXT.finditer(text):
                n = int(m.group(1) or m.group(3))
                if m.group(4):  # 文の中の「待つ」: 何を待つかの言葉があれば「マージ待ち」のようにする
                    w = WAIT_WORD.search(m.group(4))
                    phrase = f"{w.group(0)}待ち" if w else "待ち"
                else:
                    phrase = m.group(2)
                if n == me or any(x["id"] == n and x["kind"] == "wait" for x in out):
                    continue
                line = next((l for l in text.splitlines() if m.group(0) in l), m.group(0))
                out.append({"id": n, "kind": "wait", "via": via, "phrase": phrase, "note": re.sub(r"\s+", " ", line).strip()[:160]})
        rels[me] = [x for x in out if x["kind"] != "relates"]
    others = sorted({x["id"] for v in rels.values() for x in v})
    info = {}
    for k in range(0, len(others), 50):
        try:
            for o in get(f"/issues.json?issue_id={','.join(map(str, others[k:k + 50]))}&status_id=*&limit=100"):
                st = o.get("status") or {}
                info[o["id"]] = {"status": st.get("name", ""), "closed": bool(st.get("is_closed")) or bool(o.get("closed_on")),
                                 "subject": o.get("subject", "")}
        except Exception:
            pass  # 相手の状態が取れなくても、番号だけは出す
    data = {"host": host, "fetched_at": time.time(), "issues": [
        {"id": i["id"], "subject": i.get("subject", ""), "status": (i.get("status") or {}).get("name", ""),
         "priority": (i.get("priority") or {}).get("name", ""), "updated_on": i.get("updated_on", ""),
         "relations": [{**x, **info.get(x["id"], {})} for x in rels[i["id"]]]}
        for i in issues]}
    redmine_cache.update(at=time.time(), data=data)
    return data


def ticket_places():
    """チケット番号 -> 各環境のブランチ・issue docs。

    ブランチは ticket_v2_api / ticket_v2 のローカルブランチ名に番号を含むもの（checkout 中かも付ける）。
    issue docs は各環境の docs/issues/active/<番号>_*。
    """
    places = {}
    for d, env in ENV_DIRS.items():
        root = os.path.join(HOME, "www", d)
        if not os.path.isdir(root):
            continue
        for repo in REPO_NAMES:
            path = os.path.join(root, repo)
            try:
                out = subprocess.run(["git", "-C", path, "for-each-ref", "--format=%(refname) %(objectname)",
                                      "refs/heads", "refs/remotes/origin"], capture_output=True, text=True, timeout=5).stdout
            except (OSError, subprocess.TimeoutExpired):
                continue
            heads, remotes = {}, {}
            for line in out.splitlines():
                ref, _, sha = line.partition(" ")
                if ref.startswith("refs/heads/"):
                    heads[ref[len("refs/heads/"):]] = sha
                elif ref.startswith("refs/remotes/origin/"):
                    remotes[ref[len("refs/remotes/origin/"):]] = sha
            current = branch_of(path)
            for b, sha in heads.items():
                for n in set(TICKET.findall(b)):
                    entry = {"env": env, "repo": repo, "branch": b, "current": b == current}
                    if not b.startswith("backup/"):  # 退避用は push しない前提なので調べない
                        entry["push"] = push_state(path, sha, remotes.get(b))
                    places.setdefault(n, {"branches": [], "docs": []})["branches"].append(entry)
        for doc in glob.glob(os.path.join(root, "docs", "issues", "active", "[0-9]*_*")):
            m = re.match(r"(\d{5})_", os.path.basename(doc))
            if m:
                places.setdefault(m.group(1), {"branches": [], "docs": []})["docs"].append(env)
    return places


push_cache = {}  # (リポジトリ, 手元の sha, origin の sha) -> {"ahead", "behind"}


def push_state(path, local, remote):
    """手元のブランチと origin の同名ブランチの差（最後に fetch した時点）。origin に無ければ {"remote": False}。"""
    if not remote:
        return {"remote": False}
    if local == remote:
        return {"remote": True, "ahead": 0, "behind": 0}
    key = (path, local, remote)
    if key not in push_cache:
        try:
            out = subprocess.run(["git", "-C", path, "rev-list", "--left-right", "--count", f"{local}...{remote}"],
                                 capture_output=True, text=True, timeout=5).stdout.split()
            push_cache[key] = {"ahead": int(out[0]), "behind": int(out[1])}
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
            return {"remote": True}
    return {"remote": True, **push_cache[key]}


GH_OWNER = "CoRichInc"
pr_lock = threading.Lock()
pr_cache = {"at": 0, "prs": {}}  # (リポジトリ, ブランチ) -> {"number", "state", "draft", "url"}


def refresh_prs():
    """自分が作った PR（全状態・新しい順に各 300 件）をブランチ名で引けるようにする。gh の認証を使う。"""
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    prs = {}
    for repo in REPO_NAMES:
        try:
            out = subprocess.run([gh, "pr", "list", "--repo", f"{GH_OWNER}/{repo}", "--author", "@me", "--state", "all",
                                  "--limit", "300", "--json", "number,headRefName,state,isDraft,url"],
                                 capture_output=True, text=True, timeout=30)
            rows = json.loads(out.stdout) if out.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            rows = None
        if rows is None:  # 取れなかったリポジトリは前回の結果を残す
            with pr_lock:
                prs.update({k: v for k, v in pr_cache["prs"].items() if k[0] == repo})
            continue
        for r in reversed(rows):  # 同じブランチの PR が複数あれば新しいほうで上書きする
            prs[(repo, r["headRefName"])] = {"number": r["number"], "state": r["state"].lower(),
                                             "draft": r.get("isDraft", False), "url": r["url"]}
    with pr_lock:
        pr_cache.update(at=time.time(), prs=prs)


def pr_loop():
    while True:
        try:
            refresh_prs()
        except Exception as e:
            print(f"{time.strftime('%F %T')} PR の取得に失敗: {e}", file=sys.stderr, flush=True)
        time.sleep(300)


def branch_of(repo):
    """リポジトリの今のブランチ名（.git/HEAD を読むだけ。取れなければ \"\"）。"""
    try:
        with open(os.path.join(repo, ".git", "HEAD")) as f:
            ref = f.read().strip()
    except OSError:
        return ""
    return ref.removeprefix("ref: refs/heads/") if ref.startswith("ref: ") else ""


def redmine_view():
    """担当チケットに、どの枠（セッション）・どの環境のブランチ・issue docs があるかを付ける。"""
    data = redmine_issues()
    if "error" in data:
        return data
    panes = ai_panes()
    sessions = {}
    for sl in panes.get("slots", []):
        if sl.get("ticket"):
            sessions.setdefault(sl["ticket"], []).append(
                {"slot": sl["slot"], "env": sl["env"], "kind": sl["kind"], "state": sl["state"], "skill": sl.get("skill", "")})
    places = ticket_places()
    items = []
    for i in data["issues"]:
        n = str(i["id"])
        p = places.get(n, {"branches": [], "docs": []})
        with hist_lock:
            h = sorted(hist.get(n, {}).items(), key=lambda kv: -kv[1])
        with pr_lock:
            branches = [{**b, "pr": pr_cache["prs"].get((b["repo"], b["branch"]))} for b in p["branches"]]
        items.append({**i, "url": f"{data['host']}/issues/{n}", "sessions": sessions.get(n, []),
                      "branches": branches, "docs": sorted(set(p["docs"])),
                      "history": [{"env": e, "last": t} for e, t in h]})
    return {"fetched_at": data["fetched_at"], "issues": items, "history_days": HIST_DAYS, "pr_at": pr_cache["at"]}


HIST_DAYS = 30
hist_lock = threading.Lock()
hist = {}        # チケット番号 -> {env: 最後に扱った時刻}（直近 HIST_DAYS 日、ユーザーが入力した文だけ）
hist_files = {}  # 記録ファイル -> {"offset", "cwd"}
hist_full = {}   # チケット番号 -> {"at", "result"}（全期間の検索結果。10 分覚える）


def codex_prompt_text(payload):
    """Codex の記録の1行から、ユーザーが入力した文だけを取り出す（AGENTS.md・環境情報の差し込みは除く）。"""
    if payload.get("type") != "message" or payload.get("role") != "user":
        return ""
    text = "\n".join(c.get("text", "") for c in payload.get("content") or [] if isinstance(c, dict))
    t = text.lstrip()
    if not t or t.startswith("<") or t.startswith("# AGENTS.md") or len(t) > 20000:
        return ""
    return text


def history_entries(path, kind, st, lines):
    """記録の行から (チケット番号, 環境, 時刻) を出す。env1〜env4 の作業フォルダのセッションだけ。"""
    for line in lines:
        if kind == "claude":
            if '"user"' not in line and '"cwd"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            st["cwd"] = d.get("cwd") or st.get("cwd", "")
            text = prompt_text(d)
        else:
            if '"session_meta"' in line:
                try:
                    st["cwd"] = json.loads(line).get("payload", {}).get("cwd", "")
                except ValueError:
                    pass
                continue
            if '"user"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            text = codex_prompt_text(d.get("payload") or {})
        if not text:
            continue
        env = env_of(st.get("cwd"))
        if env not in ENV_DIRS.values():
            continue  # ct-sweep の一時フォルダなど、環境の外のセッションは数えない
        ts = iso_ts(d.get("timestamp")) or os.path.getmtime(path)
        for n in set(PROMPT_TICKET.findall(text)):
            yield n, env, ts, kind


def history_files(days=None):
    files = [(f, "claude") for f in glob.glob(os.path.join(HOME, ".claude", "projects", "*", "*.jsonl"))]
    files += [(f, "codex") for f in glob.glob(os.path.join(HOME, ".codex", "sessions", "*", "*", "*", "*.jsonl"))]
    if days:
        limit = time.time() - days * 86400
        files = [(f, k) for f, k in files if os.path.getmtime(f) >= limit]
    return files


def scan_history_once():
    for path, kind in history_files(HIST_DAYS):
        st = hist_files.setdefault(path, {"offset": 0, "cwd": ""})
        try:
            lines = read_new_lines(path, st)
        except OSError:
            continue
        found = list(history_entries(path, kind, st, lines))
        with hist_lock:
            for n, env, ts, _ in found:
                cur = hist.setdefault(n, {})
                cur[env] = max(cur.get(env, 0), ts)
    limit = time.time() - HIST_DAYS * 86400
    with hist_lock:
        for n in list(hist):
            hist[n] = {e: t for e, t in hist[n].items() if t >= limit}
            if not hist[n]:
                del hist[n]


def history_loop():
    while True:
        try:
            scan_history_once()
        except Exception as e:  # 集め損ねても次の回でやり直す
            print(f"{time.strftime('%F %T')} 履歴の収集に失敗: {e}", file=sys.stderr, flush=True)
        time.sleep(60)


def history_full(n):
    """1 チケットを全期間で探す: 残っている Claude・Codex の記録全部と、各環境の git のコミット（refs #番号）。"""
    cached = hist_full.get(n)
    if cached and time.time() - cached["at"] < 600:
        return cached["result"]
    sessions = {}
    needle = n.encode()
    for path, kind in history_files():
        try:
            with open(path, "rb") as f:
                if needle not in f.read():
                    continue
            st = {"offset": 0, "cwd": ""}
            lines = read_new_lines(path, st)
        except OSError:
            continue
        for tn, env, ts, k in history_entries(path, kind, st, lines):
            if tn == n:
                key = f"{env} {k}"
                sessions[key] = max(sessions.get(key, 0), ts)
    commits = {}
    for d, env in ENV_DIRS.items():
        root = os.path.join(HOME, "www", d)
        for repo in ("", *REPO_NAMES):
            path = os.path.join(root, repo) if repo else root
            if not os.path.isdir(os.path.join(path, ".git")):
                continue
            try:
                out = subprocess.run(["git", "-C", path, "log", "--all", "-E", f"--grep=#{n}([^0-9]|$)", "--format=%ct"],
                                     capture_output=True, text=True, timeout=20).stdout.split()
            except (OSError, subprocess.TimeoutExpired):
                continue
            if out:
                key = f"{env} {repo or 'workspace'}"
                commits[key] = {"last": max(map(int, out)), "count": len(out)}
    result = {"ticket": n, "sessions": [{"where": k, "last": v} for k, v in sorted(sessions.items(), key=lambda kv: -kv[1])],
              "commits": [{"where": k, **v} for k, v in sorted(commits.items(), key=lambda kv: -kv[1]["last"])]}
    hist_full[n] = {"at": time.time(), "result": result}
    return result


def run_action(action, env, comp):
    try:
        proc = subprocess.Popen([LOCAL_SERVER, action, env, comp], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            with job_lock:
                job["output"] += line
        rc = proc.wait()
    except OSError as e:
        rc = 1
        with job_lock:
            job["output"] += f"⚠️  起動できませんでした: {e}\n"
    with job_lock:
        job.update(running=False, rc=rc, finished=time.time())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def check_access(self):
        """接続元 IP と合言葉を確かめる。通せないときは応答を返して False。"""
        cfg = load_config()
        ip = self.client_address[0].removeprefix("::ffff:")
        if "*" not in cfg["allow_ips"] and ip not in cfg["allow_ips"]:
            print(f"{time.strftime('%F %T')} 許可していない接続元をはじきました: {ip} {self.command} {urlsplit(self.path).path}",
                  file=sys.stderr, flush=True)
            self.send_json({"error": f"この接続元（{ip}）は許可されていません"}, 403)
            return False
        key = cfg["key"]
        url = urlsplit(self.path)
        given = parse_qs(url.query).get("key", [""])[0]
        cookie = ""
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "dd_key":
                cookie = value
        if key and not (hmac.compare_digest(given, key) or hmac.compare_digest(cookie, key)):
            self.send_json({"error": "合言葉が違います。/?key=<合言葉> で開いてください"}, 403)
            return False
        self.path = url.path
        self.query = parse_qs(url.query)
        self.set_cookie = bool(key) and hmac.compare_digest(given, key)
        return True

    def do_GET(self):
        if not self.check_access():
            return
        if self.path in ("/", "/index.html"):
            with open(os.path.join(BASE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            if self.set_cookie:
                key = load_config()["key"]
                self.send_header("Set-Cookie", f"dd_key={key}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            cfg = load_config()
            self.send_json({
                "now": time.time(),
                "servers": server_status(),
                "claude": claude_usage(),
                "codex": codex_usage(cfg),
                "stale_minutes": cfg["stale_minutes"],
            })
        elif self.path == "/api/pane":
            try:
                n = int(self.query.get("slot", ["0"])[0])
            except ValueError:
                n = 0
            if not 1 <= n <= 12:
                return self.send_json({"error": "slot は 1〜12 です"}, 400)
            self.send_json(pane_text(n))
        elif self.path == "/api/links":
            try:
                offset = max(0, int(self.query.get("offset", ["0"])[0]))
                limit = min(5000, max(1, int(self.query.get("limit", ["10"])[0])))
            except ValueError:
                offset, limit = 0, 10
            if self.query.get("rescan", [""])[0] == "1":  # 枠の返答が終わった・「取り直す」: その場で集め直してから返す
                try:
                    scan_links_locked()
                except Exception as e:
                    print(f"{time.strftime('%F %T')} リンクの収集に失敗: {e}", file=sys.stderr, flush=True)
            self.send_json(links_query(self.query.get("cat", [""])[0], self.query.get("q", [""])[0].strip(), offset, limit))
        elif self.path == "/api/redmine":
            if self.query.get("refresh", [""])[0] == "1":
                redmine_cache["at"] = 0
                refresh_prs()
            self.send_json(redmine_view())
        elif self.path == "/api/history":
            n = self.query.get("ticket", [""])[0]
            if not re.fullmatch(r"\d{4,6}", n):
                return self.send_json({"error": "ticket が不正です"}, 400)
            self.send_json(history_full(n))
        elif self.path == "/api/panes":
            self.send_json(ai_panes())
        elif self.path == "/api/job":
            with job_lock:
                self.send_json(dict(job))
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.check_access():
            return
        # 別サイトのページからフォーム送信で叩かれないよう、独自ヘッダーを必須にする
        if self.headers.get("X-Dashboard") != "1":
            return self.send_json({"error": "forbidden"}, 403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self.send_json({"error": "bad request"}, 400)
        if self.path == "/api/link":
            try:
                slot = int(req.get("slot"))
                targets = sorted({int(t) for t in (req.get("targets") or [])})
            except (TypeError, ValueError):
                return self.send_json({"error": "slot / targets が不正です"}, 400)
            if not 1 <= slot <= 12 or any(not 1 <= t <= 12 or t == slot for t in targets):
                return self.send_json({"error": "連動先は自分以外の 1〜12 です"}, 400)
            body, code = set_link(slot, targets)
            return self.send_json(body, code)
        if self.path == "/api/cli":
            try:
                slot = int(req.get("slot"))
            except (TypeError, ValueError):
                return self.send_json({"error": "slot が不正です"}, 400)
            if not 1 <= slot <= 12:
                return self.send_json({"error": "slot は 1〜12 です"}, 400)
            # 同じ枠に2回送らないよう、起動・停止は1つずつ
            if not cli_lock.acquire(blocking=False):
                return self.send_json({"error": "別の起動・停止を実行中です"}, 409)
            try:
                if req.get("action") == "launch":
                    body, code = cli_launch(slot, req.get("kind"), req.get("mode", "new"))
                elif req.get("action") == "stop":
                    body, code = cli_stop(slot)
                else:
                    body, code = {"error": "action が不正です"}, 400
            finally:
                cli_lock.release()
            return self.send_json(body, code)
        if self.path != "/api/run":
            return self.send_json({"error": "not found"}, 404)
        action, env, comp = req.get("action"), req.get("env"), req.get("comp", "all")
        if action not in ACTIONS or env not in ENVS or comp not in COMPS:
            return self.send_json({"error": "action / env / comp が不正です"}, 400)
        with job_lock:
            if job["running"]:
                return self.send_json({"error": f"{job['target']} を実行中です"}, 409)
            job.update(running=True, target=f"{env} {comp} の{ACTIONS[action]}", output="", rc=None, started=time.time(), finished=None)
        threading.Thread(target=run_action, args=(action, env, comp), daemon=True).start()
        self.send_json({"ok": True})


def main():
    cfg = load_config()
    if not cfg["key"]:
        sys.exit("config.json に key（合言葉）を設定してください")
    threading.Thread(target=links_loop, daemon=True).start()
    threading.Thread(target=history_loop, daemon=True).start()
    threading.Thread(target=pr_loop, daemon=True).start()
    httpd = ThreadingHTTPServer((cfg["bind"], cfg["port"]), Handler)
    print(f"dev-dashboard: {cfg['bind']}:{cfg['port']} 許可: {', '.join(cfg['allow_ips'])}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
