#!/usr/bin/env python3
"""開発ダッシュボード（自宅 LAN 向けの小さな Web サーバー）。

  GET  /             … index.html
  GET  /api/status   … 環境1・2のサーバー状態 + Claude / Codex の使用率
  POST /api/run      … ~/bin/local-server <up|down|restart> <env> <comp> を裏で実行
  GET  /api/pane     … [n] の枠の画面の文字と、起動できるモード
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
    if not isinstance(content, str) or content.lstrip().startswith("<"):
        return ""
    return content


def claude_ticket(pane_id):
    """Claude 用: その枠のセッションでユーザーが入力した文に出てくる番号のうち一番多いもの。

    枠とセッションの対応は statusline.py が cache/pane-<id>.json に書く。
    画面やブランチは使わない（画面は話題に出ただけの番号を拾い、ブランチは環境で1つなので新しいセッションにも付く）。
    """
    try:
        with open(os.path.join(CACHE, f"pane-{pane_id.lstrip('%')}.json")) as f:
            path = json.load(f)["transcript_path"]
        size = os.path.getsize(path)
    except (OSError, ValueError, KeyError):
        return ""
    st = transcript_cache.setdefault(path, {"offset": 0, "counts": {}})
    if size < st["offset"]:
        st.update(offset=0, counts={})
    if size > st["offset"]:
        with open(path, "rb") as f:
            f.seek(st["offset"])
            chunk = f.read()
        last_nl = chunk.rfind(b"\n")
        if last_nl >= 0:
            st["offset"] += last_nl + 1
            for line in chunk[:last_nl].decode("utf-8", "replace").splitlines():
                if '"user"' not in line:
                    continue
                try:
                    text = prompt_text(json.loads(line))
                except ValueError:
                    continue
                for n in PROMPT_TICKET.findall(text):
                    st["counts"][n] = st["counts"].get(n, 0) + 1
    c = st["counts"]
    return max(c, key=c.get) if c else ""


def running_kinds():
    """端末（tty）ごとに、動いている AI CLI（claude / codex）を返す。ps を1回だけ呼ぶ。

    枠のタイトルは tmuxp で決めた「その枠の既定の CLI」なので、別の CLI を起動した枠もある。実際のプロセスで見る。
    """
    kinds = {}
    try:
        out = subprocess.run(["ps", "-A", "-o", "tty=,comm="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return kinds
    for line in out.splitlines():
        tty, _, comm = line.strip().partition(" ")
        name = os.path.basename(comm.strip())
        if name in ("claude", "codex"):
            kinds.setdefault(tty, set()).add(name)
    return kinds


def pane_status(pane_id, cmd, ai_state, tty, slot_kind, kinds):
    """(動いている CLI の種類, 状態) を返す。止まっていれば種類は枠の既定。"""
    # CLI はラッパーの bash から起動されるので、ログインシェル（zsh）に戻っていれば止まっている
    if cmd == "zsh":
        return slot_kind, "stopped"
    found = kinds.get(tty.removeprefix("/dev/"), set())
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
                   "#{window_name}\t#{pane_id}\t#{pane_current_command}\t#{@ai_state}\t#{@cm_title}\t#{pane_tty}\t#{pane_title}").stdout
        kinds = running_kinds()
    except (OSError, subprocess.TimeoutExpired):
        return {"running": False, "slots": []}
    slots = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 7 or parts[0] != "monitor":
            continue
        _, pane_id, cmd, ai_state, cm_title, tty = parts[:6]
        pane_title = "\t".join(parts[6:])
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
        if m:
            ticket = m.group(1)
        elif state == "stopped":
            ticket = ""
        else:
            ticket = claude_ticket(pane_id) if kind == "claude" else screen_ticket(pane_id)
        slots[n] = {"slot": n, "env": env, "kind": kind, "slot_kind": slot_kind, "state": state, "task": task, "ticket": ticket,
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
    httpd = ThreadingHTTPServer((cfg["bind"], cfg["port"]), Handler)
    print(f"dev-dashboard: {cfg['bind']}:{cfg['port']} 許可: {', '.join(cfg['allow_ips'])}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
