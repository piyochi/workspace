#!/usr/bin/env python3
"""開発ダッシュボード（自宅 LAN 向けの小さな Web サーバー）。

  GET  /             … index.html
  GET  /api/status   … 環境1・2のサーバー状態 + Claude / Codex の使用率
  GET  /api/sys      … Mac 本体の CPU 使用率・メモリ使用量（ヘッダーのゲージ）
  POST /api/run      … ~/bin/local-server <up|down|restart> <env> <comp> を裏で実行
  GET  /api/pane     … [n] の枠の画面の文字と、起動できるモード
  GET  /api/memo     … 自由メモ（memo.json）。POST /api/memo {text, base} で保存（base が古ければ 409）
  GET  /api/links    … AI（Claude / Codex）が出した文章の URL（直近7日・新しい順。cat=種類・q=フリーワード）
  GET  /api/redmine  … 自分担当の未完了チケット（5分キャッシュ、refresh=1 で取り直し）と、各チケットの枠・ブランチ・issue docs、
                       今日（朝 4:00 以降）の作業（today）と、今日作業した担当外・完了済みのチケット（today_extra）
  GET  /api/watch    … hub の監視（/na-order で固定したチケットの枠・段階・状態。refresh=1 でその場で判定、tickets=番号… で確かめる）
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
import datetime
import glob
import html
import urllib.parse
import urllib.request
import hmac
import io
import json
import zipfile
import sys
from urllib.parse import parse_qs, urlsplit
import os
import re
import shutil
import subprocess
import threading
import time
import fcntl
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

ENVS = ("env1", "env2", "env3", "env4")
COMPS = ("api", "app", "sqs", "all")
ACTIONS = {"up": "起動", "down": "停止", "restart": "再起動"}
STATUS_LINE = re.compile(r"^([●◐○])\s+(env\d)\s+(api|app|sqs)")

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


# --- Mac 本体の CPU・メモリ（ヘッダーのゲージ用。/api/sys） ---------------------------------
import ctypes  # noqa: E402

_libc = ctypes.CDLL("/usr/lib/libSystem.dylib")
_libc.mach_host_self.restype = ctypes.c_uint
_sys_lock = threading.Lock()
_sys_cpu = {"pct": None}
VM_LINE = re.compile(r'^"?([^":]+)"?:\s+(\d+)\.', re.M)


def _cpu_ticks():
    """host_statistics(HOST_CPU_LOAD_INFO) の累計ティック [user, system, idle, nice]。取れなければ None。"""
    arr = (ctypes.c_uint * 4)()
    cnt = ctypes.c_uint(4)
    if _libc.host_statistics(_libc.mach_host_self(), 3, arr, ctypes.byref(cnt)) != 0:
        return None
    return list(arr)


def cpu_loop():
    """2秒ごとにティックの差分から CPU 使用率（全コア合計を 100% とする）を出しておく。"""
    prev = _cpu_ticks()
    while True:
        time.sleep(2)
        cur = _cpu_ticks()
        if prev and cur:
            d = [(b - a) & 0xFFFFFFFF for a, b in zip(prev, cur)]
            total = sum(d)
            if total:
                with _sys_lock:
                    _sys_cpu["pct"] = round(100 * (d[0] + d[1] + d[3]) / total, 1)
        prev = cur


def _sysctl(name):
    return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=3).stdout.strip()


def sys_usage():
    """CPU 使用率とメモリ使用量。

    メモリはアクティビティモニタの「使用済みメモリ」と同じ計算（アプリ用 = 匿名 - パージ可能、+ 固定、+ 圧縮）。
    pressure は Mac のメモリ圧迫レベル（1=正常 2=警告 4=危険）。取れない値は None にしてゲージを空にする。
    """
    with _sys_lock:
        cpu = _sys_cpu["pct"]
    mem = None
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
        page = int(re.search(r"page size of (\d+)", out).group(1))
        v = {m.group(1): int(m.group(2)) for m in VM_LINE.finditer(out)}
        total = int(_sysctl("hw.memsize"))
        used = (v["Anonymous pages"] - v["Pages purgeable"] + v["Pages wired down"]
                + v["Pages occupied by compressor"]) * page
        mem = {"used": used, "total": total, "pct": round(100 * used / total, 1),
               "pressure": int(_sysctl("kern.memorystatus_vm_pressure_level") or 1)}
    except (OSError, ValueError, KeyError, AttributeError, subprocess.SubprocessError) as e:
        print(f"{time.strftime('%F %T')} メモリ使用量を取れませんでした: {e}", file=sys.stderr, flush=True)
    return {"cpu": cpu, "mem": mem}


MEMO_FILE = os.path.join(BASE, "memo.json")  # 自由メモ（ダッシュボードの「メモ」欄）。cache/ と分けて、消してよいものと混ぜない
MEMO_MAX = 100_000
memo_lock = threading.Lock()


def memo_read():
    try:
        with open(MEMO_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return {"text": str(d.get("text", "")), "updated": float(d.get("updated") or 0)}
    except (OSError, ValueError):
        return {"text": "", "updated": 0}


def memo_write(text, base):
    """base: 画面が読み込んだときの updated。別の画面が先に保存していたら上書きせず 409 で今の内容を返す。
    電源断で壊れないよう、一時ファイルに書いて fsync してから置き換える。"""
    with memo_lock:
        cur = memo_read()
        if base is not None and abs(float(base) - cur["updated"]) > 1e-6:
            return {"error": "別の画面でメモが更新されています", **cur}, 409
        new = {"text": text, "updated": time.time()}
        tmp = MEMO_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, MEMO_FILE)
        try:
            fd = os.open(BASE, os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        except OSError:
            pass
        return new, 200


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
            # ◐ = 動いているが枠から外れている（docker compose up が落ちた等）。画面では黄色
            envs.setdefault(m.group(2), {})[m.group(3)] = {"●": True, "◐": "detached", "○": False}[m.group(1)]
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


USAGE_API = "https://api.anthropic.com/api/oauth/usage"
USAGE_TTL = 300  # モデル別の枠は 5 分に 1 回だけ取りに行く（失敗も同じ間は取り直さない）
scoped_lock = threading.Lock()
scoped_cache = {}  # 設定フォルダ -> {"at": 取得時刻, "windows": {"Fable": {percent, resets_at}}}


def claude_scoped_windows(cdir):
    """モデル別の週の枠（Fable など）。statusline には来ないので、/usage 画面と同じ API から取る。

    トークンは設定フォルダの .credentials.json を読むだけ（更新は Claude Code に任せる。期限切れの間は前回の値を出す）。
    公開されていない API なので、形が変わったら何も出さない。
    """
    with scoped_lock:
        c = scoped_cache.get(cdir)
        if c and time.time() - c["at"] < USAGE_TTL:
            return c["windows"]
        prev = c["windows"] if c else {}
        scoped_cache[cdir] = {"at": time.time(), "windows": prev}  # 取得中・失敗のあいだは前回の値
    import urllib.request
    try:
        with open(os.path.join(cdir, ".credentials.json")) as f:
            token = (json.load(f).get("claudeAiOauth") or {}).get("accessToken")
        if not token:
            return prev
        req = urllib.request.Request(USAGE_API, headers={
            "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20", "User-Agent": "dev-dashboard"})
        with urllib.request.urlopen(req, timeout=5) as r:
            limits = json.load(r).get("limits") or []
        wins = {}
        for lim in limits:
            if not isinstance(lim, dict) or lim.get("kind") != "weekly_scoped":
                continue
            scope = lim.get("scope") or {}
            name = (scope.get("model") or {}).get("display_name") or scope.get("surface")
            w = window({"used_percent": lim.get("percent"), "resets_at": lim.get("resets_at")})
            if isinstance(name, str) and name and w:
                wins[name] = w
    except (OSError, ValueError, AttributeError):
        return prev
    with scoped_lock:
        scoped_cache[cdir] = {"at": time.time(), "windows": wins}
    return wins


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
                **(claude_scoped_windows(d["config_dir"]) if d.get("config_dir") else {}),
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
# MAIN の枠で動く hub（環境1〜4の12枠の取りまとめ役。2026-11-25〜。説明は ~/.local/share/ticket-v2/hub/README.md）
HUB_DIR = os.path.join(HOME, "www", "ticket_v2_hub")
HUB_CLAUDE_CMD = "bin/claude ticket_v2 ticket_v2_api --permission-mode auto"
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
# スキルの引数（/ct-redmine 14625 14891）は # が無くても番号とみなす
PROMPT_TICKET = re.compile(r"(?<![\d.])#?(\d{5})(?!\d)")
# 依頼文の地の文は「#番号」だけ（貼ったメールの「17767件」などを拾わない）
MENTION_TICKET = re.compile(r"[#＃](\d{5})(?!\d)")
REDMINE_MISSING = set()  # Redmine に問い合わせて見つからなかった番号（今日の作業・日報の候補から外す）
transcript_lock = threading.RLock()  # 画面の更新と Redmine 欄が同時に読むと、片方が読み進めた分をもう片方が見落とす
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


def is_question(text):
    """返答の最後の行が質問（？・? で終わる）か。スキルが答えを待っているのか、終わったのかの見分けに使う。"""
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return bool(lines) and lines[-1].strip().rstrip("*_`)）」』 ").endswith(("？", "?"))


def claude_session_info(pane_id):
    with transcript_lock:
        return _claude_session_info(pane_id)


def _claude_session_info(pane_id):
    """Claude 用: その枠のセッションの (チケット番号, 最後に使った ct- のスキル)。

    チケット番号は、作業の番号と分かる入力（work_ticket）のうち一番新しいもの。話に出ただけの番号は拾わない。スキルは Skill ツールの呼び出しか
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
        return "", "", False, []  # 通常の戻り値（番号・スキル・スキル完了・番号の一覧）と同じ 4 つ
    counts = st.setdefault("counts", {})
    skills = None
    for line in lines:
        if '"user"' in line:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            text = prompt_text(entry)
            for n in MENTION_TICKET.findall(text):
                counts[n] = counts.get(n, 0) + 1
            tks = claude_work_tickets(entry)
            if tks:
                st["ticket"] = tks[0]  # 作業の番号が出た入力のうち一番新しいもの（今やっているチケット）
                st["tickets"] = tks  # スキルに番号を並べたときは全部（Redmine 欄・メモで全部に色を付ける）
            if "<command-name>" in line:
                skills = skills or known_skills()
                for name in SKILL_CMD.findall(json.dumps(entry.get("message", {}), ensure_ascii=False)):
                    if name.startswith("ct-") and name in skills:
                        st["skill"], st["skill_done"] = name, False
        if '"name":"Skill"' in line:
            m = re.search(r'"name":"Skill","input":\{"skill":"([^"]+)"', line)
            if m and m.group(1).startswith("ct-"):
                st["skill"], st["skill_done"] = m.group(1), False
        # スキルを使ったあと、返答の区切り（end_turn）が質問で終わっていなければ、スキルは終わったとみなす。
        # 質問で終わったとき（答え待ち）は、次の区切りで見直す。一度終わったら、次のスキルまで終わったまま
        if st.get("skill") and not st.get("skill_done") and '"end_turn"' in line and '"assistant"' in line:
            try:
                msg = json.loads(line).get("message") or {}
            except ValueError:
                continue
            if msg.get("stop_reason") == "end_turn":
                text = "\n".join(b.get("text", "") for b in msg.get("content") or [] if isinstance(b, dict) and b.get("type") == "text")
                if not is_question(text):
                    st["skill_done"] = True
    return st.get("ticket", ""), st.get("skill", ""), st.get("skill_done", False), st.get("tickets", [])


codex_rollouts = {}  # codex の pid -> 記録ファイル（lsof は重いので pid ごとに1回）


def codex_skill(tty, kinds_pids):
    with transcript_lock:
        return _codex_skill(tty, kinds_pids)


def _codex_skill(tty, kinds_pids):
    """Codex 用: 動いている Codex の記録ファイルから、最後に SKILL.md を読んだスキル名。取れなければ ""。

    Codex にはスキルを使った記録がはっきり残らないので、コマンド実行（exec）で skills/<名前>/SKILL.md を
    読んだものをスキルを使ったと見なす（推測）。
    """
    pid = kinds_pids.get(tty, {}).get("codex")
    if not pid:
        return "", False
    if pid not in codex_rollouts:
        try:
            out = subprocess.run(["lsof", "-p", pid, "-Fn"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        paths = [l[1:] for l in out.splitlines() if l.startswith("n") and "/rollout-" in l and l.endswith(".jsonl")]
        codex_rollouts[pid] = max(paths, key=os.path.getmtime) if paths else ""
    path = codex_rollouts[pid]
    if not path:
        return "", False
    st = transcript_cache.setdefault(path, {"offset": 0})
    try:
        lines = read_new_lines(path, st)
    except OSError:
        return st.get("skill", ""), st.get("skill_done", False)
    for line in lines:
        if '"token_count"' in line and '"model_context_window"' in line:  # 会話の大きさ（tmux 欄の context %）
            try:
                info = (json.loads(line).get("payload") or {}).get("info") or {}
                last, size = info.get("last_token_usage") or {}, info.get("model_context_window") or 0
                if size:
                    st["ctx"] = {"used": int(last.get("total_tokens") or 0), "size": int(size)}
            except (ValueError, TypeError, AttributeError):
                pass
            continue
        # 区切り（task_complete）の最後の返答が質問でなければ、スキルは終わったとみなす（Claude と同じ）
        if '"task_complete"' in line and st.get("skill") and not st.get("skill_done"):
            try:
                last = (json.loads(line).get("payload") or {}).get("last_agent_message") or ""
            except ValueError:
                continue
            if not is_question(last):
                st["skill_done"] = True
            continue
        if "SKILL.md" not in line or '"response_item"' not in line:
            continue
        try:
            payload = json.loads(line).get("payload", {})
        except ValueError:
            continue
        if payload.get("type") in ("custom_tool_call", "function_call"):
            m = SKILL_MD.search(json.dumps(payload.get("input") or payload.get("arguments") or "", ensure_ascii=False))
            if m and m.group(1).startswith("ct-"):
                st["skill"], st["skill_done"] = m.group(1), False
    return st.get("skill", ""), st.get("skill_done", False)


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


SUBAGENT_DIR = os.path.join(HOME, ".local", "share", "dev-dashboard", "cache", "subagents")
SUBAGENT_STALE = 15 * 60  # SubagentStop が来ないまま（中断・強制終了）この秒数、道具を使っていなければ数えない


subagent_paths = {}  # agent_id -> サブエージェントの会話の記録（jsonl）のパス


def subagent_finished(agent_id):
    """サブエージェントの記録の最後の行で、終わったかを見る。
    中断（Esc・停止）では SubagentStop が来ないので、印が残って「処理中」のままになるのを防ぐ。
    終わった: 最後が assistant の end_turn / 「[Request interrupted」。記録が見つからなければ判断しない（False）"""
    path = subagent_paths.get(agent_id)
    if not path or not os.path.exists(path):
        found = glob.glob(os.path.join(HOME, ".claude", "projects", "*", "*", "subagents", f"agent-{agent_id}.jsonl"))
        if not found:
            return False
        path = subagent_paths[agent_id] = found[0]
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            lines = [l for l in f.read().splitlines() if l.strip()]
        last = json.loads(lines[-1]) if lines else {}
    except (OSError, ValueError):
        return False
    msg = last.get("message") or {}
    if last.get("type") == "assistant" and msg.get("stop_reason") in ("end_turn", "stop_sequence", "max_tokens"):
        return True
    content = msg.get("content")
    if last.get("type") == "user" and isinstance(content, list) and content and content[0].get("type") == "text":
        return str(content[0].get("text", "")).startswith("[Request interrupted")
    return False


def running_subagents(pane_id):
    """枠の Claude で動いているサブエージェントの数（~/bin/tmux-ai-state が SubagentStart〜Stop の間ファイルを置く）。"""
    d = os.path.join(SUBAGENT_DIR, pane_id.removeprefix("%"))
    now, n, removed = time.time(), 0, False
    try:
        for name in os.listdir(d):
            p = os.path.join(d, name)
            try:
                if subagent_finished(name):
                    os.remove(p)
                    subagent_paths.pop(name, None)
                    removed = True
                elif now - os.path.getmtime(p) < SUBAGENT_STALE:
                    n += 1
                else:
                    os.remove(p)
                    removed = True
            except OSError:
                pass
    except OSError:
        pass
    if removed:  # 枠のタイトルの色（@ai_sub）も合わせる。消し忘れでオレンジのまま残らないように
        if n:
            tmux("set-option", "-p", "-t", pane_id, "@ai_sub", str(n))
        else:
            tmux("set-option", "-p", "-u", "-t", pane_id, "@ai_sub")
    return n


def pane_status(pane_id, cmd, ai_state, tty, slot_kind, kinds):
    """(動いている CLI の種類, 状態) を返す。止まっていれば種類は枠の既定。"""
    # CLI はラッパーの bash から起動されるので、ログインシェル（zsh）に戻っていれば止まっている。
    # ただし CLI がコマンドを実行している間も手前は「zsh -c」になるので、その端末に CLI のプロセスがあれば動いている
    found = kinds.get(tty.removeprefix("/dev/"), {})
    if cmd == "zsh" and not found:
        return slot_kind, "stopped"
    kind = "codex" if "codex" in found and "claude" not in found else ("claude" if "claude" in found else slot_kind)
    if kind == "claude":
        if ai_state in ("busy", "wait"):
            return kind, ai_state
        # 本体は入力待ちでも、バックグラウンドのサブエージェントが動いていれば処理中
        return kind, ("busy" if running_subagents(pane_id) else "idle")
    return kind, codex_state(pane_id)


def label_tickets(label):
    """タイトルの先頭に並んだ「#番号」全部（「#14625 #14891: 件名 / 件名」→ 14625・14891）。件名の中の番号は拾わない。"""
    m = re.match(r"\s*((?:[#＃]\d{4,6}(?!\d)[\s,、]*)+)", label or "")
    return list(dict.fromkeys(re.findall(r"[#＃](\d{4,6})", m.group(1)))) if m else []


def claude_context(pane_id):
    """Claude の枠の会話の大きさ {used, size, pct}。statusline.py が cache/pane-<id>.json に残した context_window を読む。"""
    try:
        with open(os.path.join(CACHE, f"pane-{pane_id.lstrip('%')}.json")) as f:
            cw = json.load(f).get("context_window") or {}
        u, size = cw.get("current_usage") or {}, int(cw.get("context_window_size") or 0)
    except (OSError, ValueError, TypeError):
        return None
    if not size:
        return None
    used = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    pct = cw.get("used_percentage")
    return {"used": used, "size": size, "pct": round(pct if isinstance(pct, (int, float)) else used * 100 / size)}


def codex_context(tty, kinds_pids):
    """Codex の枠の会話の大きさ {used, size, pct}。記録ファイルの直近の token_count（codex_skill が読む）から。"""
    pid = kinds_pids.get(tty, {}).get("codex")
    with transcript_lock:
        c = (transcript_cache.get(codex_rollouts.get(pid) or "") or {}).get("ctx") if pid else None
    if not c:
        return None
    return {**c, "pct": round(c["used"] * 100 / c["size"])}


def ai_panes():
    """tmuxp（ticket_v2_project）の monitor タブの [1]〜[12]（Claude / Codex）の稼働状態。

    状態: busy 処理中 / wait 許可・回答待ち / idle 入力待ち / stopped CLI が動いていない
    フォーカス中の枠は「★ FOCUS [n] ...」、元の位置は「[n] → left」になるので後者は飛ばす。
    """
    try:
        if tmux("has-session", "-t", TMUX_SESSION).returncode != 0:
            return {"running": False, "slots": []}
        out = tmux("list-panes", "-s", "-t", TMUX_SESSION, "-F",
                   "#{window_name}\t#{pane_id}\t#{pane_current_command}\t#{@ai_state}\t#{@cm_title}\t#{pane_tty}\t#{@link_slot}\t#{@ai_label}\t#{pane_current_path}\t#{pane_title}").stdout
        kinds = running_kinds()
        env_slots = codex_slots(kinds)
    except (OSError, subprocess.TimeoutExpired):
        return {"running": False, "slots": []}
    slots = {}
    main = None
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 10 or parts[0] != "monitor":
            continue
        _, pane_id, cmd, ai_state, cm_title, tty, link_slot, label, path = parts[:9]
        pane_title = "\t".join(parts[9:])
        # MAIN（hub）の枠: monitor タブで ~/www/ticket_v2_hub にいる枠。
        # 枠をフォーカスするとタイトルが「[n] → left」に変わるので、タイトルではなく場所で見つける
        if (path == HUB_DIR or path.startswith(HUB_DIR + "/")) and main is None:
            kind, state = pane_status(pane_id, cmd, ai_state, tty, "claude", kinds)
            main = {"pane": pane_id, "kind": kind, "state": state, "label": label,
                    "ctx": None if state == "stopped" else claude_context(pane_id),
                    "subagents": running_subagents(pane_id) if state != "stopped" else 0}
            continue
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
        # チケット番号は Claude は入力した文・Codex は画面の「#番号」から取り、無ければタイトルから取る
        m = TICKET.search(task)
        skill, skill_done, tickets = "", False, []
        if state == "stopped":
            ticket = ""
        elif kind == "claude":
            ticket, skill, skill_done, tickets = claude_session_info(pane_id)
        else:
            ticket = screen_ticket(pane_id)
            skill, skill_done = codex_skill(tty.removeprefix("/dev/"), kinds)
        session_ticket = ticket
        if m and not ticket:  # タイトルは最初の入力で付いたまま変わらないので、セッションから取れなかったときだけ使う
            ticket = m.group(1)
        # tmux-title・ダッシュボードで付けた文字が「#番号」で始まれば、その番号をいちばん優先する（手で付けたものなので）
        lm = re.match(r"\s*[#＃](\d{4,6})(?!\d)", label)
        label_ticket = lm.group(1) if lm else ""
        if label_ticket:
            ticket = label_ticket
        # 枠で作業中のチケット全部（先頭は ticket）。ラベルに「#14625 #14891」と並べたときはラベルの番号を全部
        if label_ticket:
            tickets = label_tickets(label)
        tickets = list(dict.fromkeys(([ticket] if ticket else []) + [t for t in tickets if ticket]))
        # 連動先: ダッシュボードで付けた印（@link_slot）を優先し、無ければ Claude の起動時の CODEX_SLOT
        link = None
        marked = parse_link_slots(link_slot)
        if marked:
            link = {"slots": marked, "from": "dashboard"}
        elif state != "stopped" and env_slots.get(tty.removeprefix("/dev/")):
            link = {"slots": [int(env_slots[tty.removeprefix("/dev/")])], "from": "codex_slot"}
        subagents = running_subagents(pane_id) if kind == "claude" and state != "stopped" else 0
        ctx = None if state == "stopped" else (claude_context(pane_id) if kind == "claude" else codex_context(tty.removeprefix("/dev/"), kinds))
        slots[n] = {"slot": n, "pane": pane_id, "env": env, "kind": kind, "slot_kind": slot_kind, "state": state, "task": task, "ticket": ticket,
                    "tickets": tickets,
                    "label": label,
                    "subagents": subagents, "ctx": ctx,
                    "skill": skill, "skill_done": skill_done, "link": link,
                    "ticket_from": "label" if label_ticket else ("title" if m and ticket == m.group(1) and not session_ticket else ("session" if ticket else ""))}
    return {"running": True, "slots": [slots[k] for k in sorted(slots)], "main": main}


# ---- tmux の枠のタイトルの文字（@ai_label） ----
# ~/bin/tmux-title・スキル ct-tmux-title・ダッシュボードの tmux 欄で付ける。枠のタイトルには claude-monitor の pane-border-format が出す。
# Claude・Codex を閉じた枠（stopped）からは外して、タイトルを元に戻す
LABEL_MAX = 200


def set_pane_label(pane, label):
    if label:
        tmux("set-option", "-p", "-t", pane, "@ai_label", label[:LABEL_MAX])
    else:
        tmux("set-option", "-p", "-u", "-t", pane, "@ai_label")
    for c in tmux("list-clients", "-F", "#{client_name}").stdout.split():
        tmux("refresh-client", "-t", c)


pane_was_running = {}  # 枠 -> 前に見たとき Claude・Codex が動いていたか
pane_last_label = {}  # 枠 -> 前に見たときのタイトル
LABEL_HIST_FILE = os.path.join(CACHE, "pane_label_history.json")
LABEL_HIST_MAX = 10
label_hist_lock = threading.Lock()


def label_histories():
    """枠の番号（"1"〜"12"）-> 付けたタイトル（新しい順）。"""
    try:
        with open(LABEL_HIST_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):  # 枠ごとに分ける前の形（全部まとめた一覧）は捨てる
        return {}
    return {str(k): [x for x in v if isinstance(x, str)][:LABEL_HIST_MAX] for k, v in d.items() if isinstance(v, list)}


def label_history(slot):
    return label_histories().get(str(slot), [])


def remember_label(slot, label):
    """付けたタイトルを枠（[1]〜[12]）ごとに新しい順で 10 件覚える（詳細画面の入力欄で選べるように）。
    tmux-title・スキルで付けたものも 10 秒ごとに拾う。"""
    if not label:
        return
    with label_hist_lock:
        d = label_histories()
        h = d.get(str(slot), [])
        if h and h[0] == label:
            return
        d[str(slot)] = ([label] + [x for x in h if x != label])[:LABEL_HIST_MAX]
        try:
            os.makedirs(CACHE, exist_ok=True)
            with open(LABEL_HIST_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(LABEL_HIST_FILE + ".tmp", LABEL_HIST_FILE)
        except OSError:
            pass


def clear_stopped_labels():
    """Claude・Codex が「動いている → 止まった」に変わった枠だけ外す（止まっている枠に手で付けたものは残す）。"""
    for sl in ai_panes().get("slots", []):
        if sl.get("label") and pane_last_label.get(sl["pane"]) != sl["label"]:  # 付け替わったときだけ覚える
            remember_label(sl["slot"], sl["label"])
        pane_last_label[sl["pane"]] = sl.get("label", "")
        running = sl["state"] != "stopped"
        if not running and pane_was_running.get(sl["pane"]) and sl.get("label"):
            set_pane_label(sl["pane"], "")
        pane_was_running[sl["pane"]] = running


def pane_label_loop():
    while True:
        try:
            if tmux("has-session", "-t", TMUX_SESSION).returncode == 0:
                clear_stopped_labels()
        except Exception as e:
            print(f"{time.strftime('%F %T')} 枠のタイトルの文字を外せませんでした: {e}", file=sys.stderr, flush=True)
        time.sleep(10)


MONITOR_TXT = os.path.join(HOME, ".tmuxp", "ticket_v2_project", "monitor.txt")
# 起動のしかた。Claude は --continue、Codex は resume --last で前回の続き
CLI_MODES = {
    "claude": {"new": "", "continue": "--continue"},
    "codex": {"new": "", "resume": "resume --last"},
}
CLI_ALL_FLAGS = re.compile(r"\s+(--continue|resume\s+--last)\b")
cli_lock = threading.Lock()


def slot_pane(n):
    """monitor タブの [n] の枠（フォーカス中なら「★ FOCUS [n]」の方）。無ければ None。
    n = 0 は MAIN（hub）の枠（~/www/ticket_v2_hub にいる枠。タイトルは変わるので場所で見る）。"""
    out = tmux("list-panes", "-s", "-t", TMUX_SESSION, "-F",
               "#{window_name}\t#{pane_id}\t#{@cm_title}\t#{pane_current_command}\t#{@ai_state}\t#{pane_tty}\t#{pane_current_path}").stdout
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 7 or parts[0] != "monitor":
            continue
        if n == 0:
            if parts[6] == HUB_DIR or parts[6].startswith(HUB_DIR + "/"):
                kind, state = pane_status(parts[1], parts[3], parts[4], parts[5], "claude", running_kinds())
                return {"id": parts[1], "title": "★ MAIN hub", "kind": kind, "slot_kind": "claude", "state": state}
            continue
        if "→ left" in parts[2]:
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
    if n == 0:  # MAIN（hub）: monitor.txt に無いので ~/.tmuxp/ticket_v2_project.yaml の履歴に積むコマンドと同じものを使う
        if kind != "claude" or mode not in CLI_MODES["claude"]:
            return None
        extra = CLI_MODES["claude"][mode]
        return HUB_DIR, HUB_CLAUDE_CMD + (f" {extra}" if extra else "")
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
    # 枠の既定の CLI を先に並べる。MAIN（n = 0）は Claude だけ
    order = ["claude"] if n == 0 else [p["slot_kind"]] + [k for k in CLI_MODES if k != p["slot_kind"]]
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


SEND_CMD = re.compile(r"/[a-z][a-z0-9:-]{1,40}")
SEND_STATES = {"busy": "処理中", "wait": "確認待ち", "stopped": "停止中"}


skills_cache = {"at": 0, "rows": []}


def skill_list():
    """送る画面のコマンドの候補: 各環境の .claude/skills・.claude/commands と ~/.claude/skills のスキル名と説明。10 分覚える。"""
    if skills_cache["rows"] and time.time() - skills_cache["at"] < 600:
        return skills_cache["rows"]
    # MAIN（hub）の .claude も見る（/na-to・/na-list は hub だけにある。where = "hub" で MAIN 宛てのときだけ候補に出す）
    roots = [os.path.join(HOME, ".claude")] + [os.path.join(HOME, "www", d, ".claude") for d in ENV_DIRS] + [os.path.join(HUB_DIR, ".claude")]
    found, where = {}, {}
    for root in roots:
        place = "home" if root == roots[0] else ("hub" if root == roots[-1] else "project")
        files = glob.glob(os.path.join(root, "skills", "*", "SKILL.md")) + glob.glob(os.path.join(root, "commands", "*.md"))
        for path in files:
            name = os.path.basename(os.path.dirname(path)) if path.endswith("SKILL.md") else os.path.basename(path)[:-3]
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    head = f.read(4000)
            except OSError:
                continue
            m = re.search(r"^name:\s*(.+)$", head, re.M)
            name = (m.group(1).strip().strip("'\"") if m else name)
            d = re.search(r"^description:[ \t]*(.*)$", head, re.M)
            desc = d.group(1).strip() if d else ""
            if desc in ("|", ">", "|-", ">-"):  # 複数行の書き方（description: |）は、次の字下げした行をつなぐ
                block = re.match(r"((?:[ \t]+.*\n?)+)", head[d.end() + 1:])
                desc = " ".join(l.strip() for l in (block.group(1) if block else "").splitlines() if l.strip())
            if SEND_CMD.fullmatch("/" + name):
                where.setdefault(name, set()).add(place)
                if name not in found:
                    found[name] = desc.strip("'\"")[:160]
    # where: スキルの置き場所（home = ~/.claude・project = 各環境の .claude・both = 両方にある）
    def place_of(n):
        w = where[n] - {"hub"} or where[n]  # hub は ticket_v2_project の clone なので、環境にもあるスキルは環境側として数える
        return "both" if len(w) > 1 else next(iter(w))
    rows = [{"cmd": "/" + n, "desc": found[n], "where": place_of(n)} for n in sorted(found)]
    skills_cache.update(at=time.time(), rows=rows)
    return rows


# ---- コマンド一覧（ダッシュボードの「コマンド」欄） ----
# 説明が英語のスキルは日本語に置き換える
SKILL_DESC_JA = {
    "continuous-learning-v2": "フックでセッションを観察し、確信度つきの「直感（instinct）」を学習して、スキル・コマンド・エージェントに育てていく仕組み。",
    "strategic-compact": "作業のフェーズの区切りで、手動でコンテキストを圧縮（/compact）するよう提案する。自動圧縮で途中の文脈が切れるのを避ける。",
}
# Claude Code の組み込みコマンド（よく使うもの）
BUILTIN_COMMANDS = [
    ("/compact", "会話を要約して圧縮する（続きの作業の文脈を残したまま、使っているトークンを減らす）。後ろに要約の指示を書ける"),
    ("/clear", "会話を消して新しく始める（今までのやり取りは引き継がない）"),
    ("/resume", "前のセッションを選んで続きから再開する"),
    ("/rewind", "会話（とコードの変更）を前の時点に巻き戻す"),
    ("/context", "今のコンテキストの使い方（何にどれだけトークンを使っているか）を見る"),
    ("/usage", "プランの利用枠（5時間・週）の使用状況を見る"),
    ("/cost", "このセッションで使ったトークンと費用を見る"),
    ("/model", "使うモデルを切り替える"),
    ("/fast", "高速モードを切り替える"),
    ("/status", "バージョン・モデル・アカウント・接続状況を見る"),
    ("/config", "設定画面を開く（テーマ・モデル・通知など）"),
    ("/permissions", "道具の許可・拒否のルールを見る・変える"),
    ("/memory", "CLAUDE.md（記憶のファイル）を開いて直す"),
    ("/init", "このプロジェクトの CLAUDE.md を作る"),
    ("/agents", "サブエージェントの定義を見る・作る"),
    ("/mcp", "MCP サーバーの接続状況を見る・認証する"),
    ("/hooks", "フックの設定を見る"),
    ("/review", "プルリクエストをレビューする"),
    ("/export", "会話をファイルやクリップボードに書き出す"),
    ("/doctor", "Claude Code のインストール・設定の不具合を調べる"),
    ("/help", "使い方とコマンドの一覧を出す"),
    ("/exit", "Claude Code を終える"),
]
# カテゴリ: 上から順に名前で当てはめる（当たらなければ「その他」）
COMMAND_CATS = [
    ("Redmine・チケット", r"ct-(redmine|issue-(auto|docs|read|sync)|branch|resume|handoff|wrap-branch|commit)$|ct-redmine-"),
    ("実装・テスト", r"ct-(tdd|rspec|vitest|e2e|ci-|ship|finish|eslint|rubocop|migration|method-comments|refactor|db-snapshot|lottery-repro|event-setup|seat-extract|operation-history)|refactor-clean|test-coverage"),
    ("レビュー・検証", r"ct-(verify|review|code-review|security-review|pr-|browser-verify|mobile-verify|sheet-browser-test|issue-reconcile|ticket-login|test-site)"),
    ("調査・設計", r"ct-(analyze|architect|planner|bug-|sweep|scope|grill|paltera|tag-|slack-|slides-review)|update-codemaps|screenshot-analyzer"),
    ("サーバー・ログ・リリース", r"ct-(deploy|local-|start-server|stop-server|restart-server|co-server|ssh-|log-|mail-check|app-|flutter-build|open-consol)"),
    ("資料・共有", r"ct-(artifact|screen-walkthrough|screenshot|html-mockup|memory-share|skill-share)"),
    ("tmux・連携", r"ct-(tmux-|link)"),
]
COMMAND_BUILTIN_CAT = "Claude Code の組み込み"


def command_list():
    rows = []
    for r in skill_list():
        name = r["cmd"][1:]
        cat = next((c for c, pat in COMMAND_CATS if re.search(pat, name)), "その他")
        rows.append({"cmd": r["cmd"], "desc": SKILL_DESC_JA.get(name, r["desc"]), "cat": cat, "where": r["where"]})
    rows += [{"cmd": c, "desc": d, "cat": COMMAND_BUILTIN_CAT, "where": "builtin"} for c, d in BUILTIN_COMMANDS]
    cats = [c for c, _ in COMMAND_CATS] + ["その他", COMMAND_BUILTIN_CAT]
    counts = {c: sum(1 for r in rows if r["cat"] == c) for c in cats}
    return {"rows": rows, "cats": [[c, counts[c]] for c in cats if counts[c]]}


# ---- リンクを Windows の Edge のタブグループで開く（拡張機能は edge-ext/。/edge-ext.zip で配る） ----
TABGROUP_PAGE = r"""<!doctype html><meta charset="utf-8"><title>開発ダッシュボード → Edge</title>
<body style="font:14px system-ui;margin:2em;color:#555">開いています…
<script>
setTimeout(function () {
  var st = document.documentElement.dataset.ddExt;
  if (st === "1") return;
  try {
    var d = JSON.parse(decodeURIComponent(location.hash.slice(1)));
    if (/^https?:\/\//.test(d.url)) {
      document.body.textContent = "タブグループの拡張機能が入っていないので、そのまま開きます（~/.local/share/dev-dashboard/edge-ext を edge://extensions で読み込むとグループにまとまります）";
      setTimeout(function () { location.replace(d.url); }, 1200);
    }
  } catch (e) { document.body.textContent = "開く URL を読めませんでした"; }
}, 800);
</script>"""


def wait_ready(pane_id, timeout=60):
    """起動した CLI が入力を受け付けるまで待つ: 画面の表示が 2 秒続けて変わらなくなったら準備できたとみなす（最短 4 秒）。"""
    start, prev, stable = time.time(), None, 0
    while time.time() - start < timeout:
        time.sleep(1)
        cur = tmux("capture-pane", "-p", "-t", pane_id).stdout
        stable = stable + 1 if cur == prev and cur.strip() else 0
        prev = cur
        if stable >= 2 and time.time() - start >= 4:
            return True
    return False


def slot_send(n, cmd, tickets, launch=None, free=""):
    """[n] の枠の Claude / Codex に「<スラッシュコマンド> <チケット番号…>」を打ち込んで Enter を押す。入力待ちの枠だけ。

    止まっている枠は、launch = (kind, mode) があれば先にその CLI を起動し、入力できるようになってから送る。

    送る文は「コマンド名 チケット番号… 自由な文」。自由な文は1行だけ（改行は Enter になって途中で送られるので空白にする）。
    Enter が効かないことがあるので、動き出さなければ Enter をもう1回だけ送る。
    """
    p = slot_pane(n)
    if not p:
        return {"error": f"[{n}] の枠が見つかりません"}, 404
    text = " ".join(x for x in (cmd, *tickets, free) if x)
    if p["state"] == "stopped" and launch:
        body, code = cli_launch(n, *launch)
        if code != 200:
            return body, code
        if not body.get("ok") or not wait_ready(p["id"]):
            return {"ok": False, "message": f"{p['title']} を起動しましたが、入力できる状態を確認できませんでした。「{text}」は送っていません"}, 200
        p = slot_pane(n) or p
    if p["state"] != "idle":
        return {"error": f"{p['title']} は{SEND_STATES.get(p['state'], p['state'])}です。入力待ちの枠か、起動する CLI を選んだ停止中の枠にだけ送れます"}, 409
    tmux("send-keys", "-t", p["id"], "-l", "--", text)  # -- : 文が - で始まっても tmux のオプションと読ませない
    time.sleep(0.5)
    tmux("send-keys", "-t", p["id"], "Enter")
    for attempt in range(2):
        for _ in range(8):
            time.sleep(0.5)
            now = slot_pane(n)
            if now and now["state"] != "idle":
                return {"ok": True, "message": f"{p['title']} に「{text}」を送りました"}, 200
        if attempt == 0:
            tmux("send-keys", "-t", p["id"], "Enter")
    return {"ok": False, "message": f"{p['title']} に「{text}」を送りましたが、動き出しを確認できませんでした。画面を見てください"}, 200


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


LINE_TICKET = re.compile(r"#(\d{5})(?!\d)|/issues/(\d{5})(?!\d)")


ONLY_TICKET = re.compile(r"\s*(?:スキル[:：]\s*\S+\s*)?#?(\d{5})\s*")
SKILL_ARGS = re.compile(r"\s*[/$]?ct-[\w-]+\s+(.*)", re.S)
BRANCH_TICKET = re.compile(r"feature/(1\d{4})|(?<![\d/])(1\d{4})_\d")
HEAD_TICKET = re.compile(r"\s*[#＃](\d{5})(?!\d)")
GIT_BRANCH_TICKET = re.compile(r"^(?:feature|design)/(1\d{4})(?!\d)")


def work_ticket(text, command_args=None):
    """その入力で「このチケットの作業をする」と分かる番号。話に出ただけの番号は拾わない。

    拾うのは: スキルに渡した番号（/ct-redmine 14766・$ct-branch 14339）、番号だけの入力（14766・スキル：Redmine 14766）、
    1 行目の先頭の「#番号」と 1 行目のブランチ名（feature/14339_2・14339_2_2）。圧縮後の要約と貼り付け（<pasted_content>）の中は見ない。
    2 行目以降のブランチ名は拾わない（例文・ブランチ一覧の貼り付けなど、作業の指示ではないことが多い）。
    """
    if command_args is not None:
        return main_ticket(command_args)
    text = re.sub(r"<pasted_content\b.*?</pasted_content[^>]*>", " ", text or "", flags=re.S)
    if text.lstrip().startswith("This session is being continued from a previous conversation"):
        return ""
    m = ONLY_TICKET.fullmatch(text) or None
    if m:
        return m.group(1)
    m = SKILL_ARGS.match(text)
    if m and main_ticket(m.group(1)):
        return main_ticket(m.group(1))
    # 1 行目の先頭の「#番号」と 1 行目のブランチ名だけを作業の指示とみなす（「#14339 feature/14339_2_2 の作業を引き継いで…」）
    head = text.lstrip().split("\n", 1)[0][:120]
    m = HEAD_TICKET.match(head)
    if m:
        return m.group(1)
    m = BRANCH_TICKET.search(head)
    return (m.group(1) or m.group(2)) if m else ""


def work_tickets(text, command_args=None):
    """work_ticket と同じ判定で、スキルの引数に番号がいくつも並んでいれば全部（/ct-redmine 14625 14891 13844）。

    先頭は work_ticket の番号。引数以外（ブランチ名・1 行目の #番号）から取れたときは1件だけ。
    """
    tk = work_ticket(text, command_args)
    if not tk:
        return []
    if command_args is not None:
        args = command_args
    else:
        m = SKILL_ARGS.match(re.sub(r"<pasted_content\b.*?</pasted_content[^>]*>", " ", text or "", flags=re.S))
        args = m.group(1) if m else ""
    rest = [n for n in dict.fromkeys(arg_tickets(args)) if n != tk]
    return [tk] + rest


def claude_work_tickets(entry):
    """claude_work_ticket の複数版（スキルに並べた番号を全部）。"""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return []
    raw = json.dumps((entry.get("message") or {}).get("content"), ensure_ascii=False)
    if "<command-name>" in raw:
        return work_tickets("", prompt_text(entry))
    return work_tickets(prompt_text(entry))


def claude_work_ticket(entry):
    """Claude の記録の1行（ユーザーの入力）から work_ticket。スラッシュコマンドは引数だけを見る。"""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return ""
    raw = json.dumps((entry.get("message") or {}).get("content"), ensure_ascii=False)
    if "<command-name>" in raw:
        return work_ticket("", prompt_text(entry))
    return work_ticket(prompt_text(entry))


LEAD_TICKETS = re.compile(r"\s*((?:[#＃]?\d{5}(?!\d)[\s,、]*)+)")


def arg_tickets(text):
    """スキルの引数・入力に出た番号。「#番号」があればそれだけ。無ければ先頭に並べた番号（/ct-redmine 14625 14891）だけ。

    貼り付けたメールの「17767件」のように、文の途中の # の無い数字は拾わない。
    """
    nums = MENTION_TICKET.findall(text or "")
    if nums:
        return nums
    m = LEAD_TICKETS.match(text or "")
    return PROMPT_TICKET.findall(m.group(1)) if m else []


def main_ticket(text):
    """ユーザーの入力に出たチケット番号のうち、いちばん多く出たもの（同数なら先に出たもの）。無ければ ""。

    圧縮後の要約や貼り付けには番号がいくつも出るので、最後の番号ではなく主な番号を取る。
    """
    nums = arg_tickets(text)
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


PREV_TRANSCRIPT = re.compile(r"read the full transcript at:\s*(\S+?\.jsonl)")


def session_fallback_ticket(path, depth=0):
    """入力から番号が取れなかったセッションの代わりの番号: 作業ブランチ → 圧縮前のセッション（たどれるだけ）で入力された番号。"""
    st = links_files.get(path) or {}
    if st.get("branch_ticket"):
        return st["branch_ticket"]
    prev = st.get("prev_path")
    if not prev or depth >= 5 or prev == path:
        return ""
    pst = links_files.get(prev) or {}
    return pst.get("ticket") or session_fallback_ticket(prev, depth + 1)


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
                # 入力から番号が取れないときの代わり: 記録に残る作業ブランチ（feature/番号）
                bm = GIT_BRANCH_TICKET.match(d.get("gitBranch") or "")
                if bm:
                    st["branch_ticket"] = bm.group(1)
                tk = claude_work_ticket(d)
                if tk:
                    st["ticket"] = tk  # このあとに出た URL は、このチケットの作業で出たものとみなす
                elif d.get("type") == "user" and not st.get("prev_path"):
                    # 圧縮のあとに続いたセッションは、要約に前のセッションの記録のパスがある。そこで入力された番号を引き継ぐ
                    # （要約の中の番号は、話に出ただけの番号が多く混ざるので使わない）
                    pt = prompt_text(d) or ""
                    if d.get("isCompactSummary") or pt.lstrip().startswith("This session is being continued"):
                        pm = PREV_TRANSCRIPT.search(pt)
                        if pm:
                            st["prev_path"] = pm.group(1)
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
                        tk = work_ticket(codex_prompt_text(json.loads(line).get("payload") or {}))
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
                          f"{env_of(st.get('cwd'))} {kind}", path, st.get("ticket") or st.get("branch_ticket", ""))
    with links_lock:
        for url in [u for u, v in links.items() if v["ts"] < limit]:
            del links[url]
        # 番号が後から分かったセッション（圧縮前に出た URL・番号を入れる前に出た URL）は、そのセッションの代わりの番号で埋める
        for v in links.values():
            if not v["ticket"]:
                v["ticket"] = session_fallback_ticket(v["path"])


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
        js = get_one(issue_id).get("journals") or []
    except Exception:
        return c["notes"] if c else []
    notes = [j.get("notes") or "" for j in js if j.get("notes")]
    # 最終更新（いちばん新しい journal。ステータス変更だけのものも含む）と、最新コメント。hub の /na-redmine が使う
    last = {}
    if js:
        me = redmine_my_id()
        lj = js[-1]
        lc = next((j for j in reversed(js) if j.get("notes")), None)
        last = {"me": me is not None and (lj.get("user") or {}).get("id") == me, "on": lj.get("created_on", ""),
                "note": re.sub(r"\s+", " ", lc.get("notes") or "").strip()[:120] if lc else "",
                "note_me": bool(lc) and me is not None and (lc.get("user") or {}).get("id") == me}
    journals_cache[issue_id] = {"updated_on": updated_on, "notes": notes, "last": last}
    return notes


def journal_last(issue_id):
    """journal_notes が覚えた最終更新・最新コメント（無ければ {}）。"""
    return (journals_cache.get(issue_id) or {}).get("last") or {}


REDMINE_PROJECT_ID = 133  # tools/claude-corich/bin/redmine.sh の list と同じ（CoRichチケット！）
REDMINE_OPEN = ("新規登録", "進行中", "フィードバック", "ﾌｨｰﾄﾞﾊﾞｯｸ")
REDMINE_WATCH_EXCLUDE = ("終了", "解決", "却下")  # ウォッチ分で出さないステータス
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


def redmine_call(path, method="GET", body=None):
    """Redmine の REST API を1回呼ぶ。応答の JSON（本文が空なら {}）を返す。"""
    import urllib.request
    host, key = redmine_creds()
    if not host or not key:
        raise OSError("REDMINE_HOST / REDMINE_API_KEY が見つかりません")
    req = urllib.request.Request(f"{host}{path}", method=method, headers={"X-Redmine-API-Key": key, "Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
    return json.loads(raw) if raw.strip() else {}


def redmine_statuses(issue_id):
    """そのチケットで選べるステータス（ワークフローで許されているもの）。取れない版の Redmine では全ステータス。"""
    try:
        issue = redmine_call(f"/issues/{issue_id}.json?include=allowed_statuses").get("issue", {})
        allowed = issue.get("allowed_statuses")
        if allowed is None:
            allowed = redmine_call("/issue_statuses.json").get("issue_statuses", [])
        cur = issue.get("status") or {}
        return {"current": cur.get("id"), "statuses": [{"id": s["id"], "name": s["name"]} for s in allowed]}, 200
    except Exception as e:
        return {"error": f"ステータスの一覧を取れませんでした: {e}"}, 502


def redmine_issue(issue_id):
    """チケット1件の番号・件名・ステータス。メモの # の候補で、Redmine 欄に無い番号を引くときに使う。"""
    try:
        i = redmine_call(f"/issues/{issue_id}.json").get("issue", {})
    except Exception as e:
        return {"error": f"#{issue_id} を取れませんでした: {e}"}, 404 if "404" in str(e) else 502
    return {"id": i.get("id"), "subject": i.get("subject", ""), "status": (i.get("status") or {}).get("name", ""),
            "closed": bool((i.get("status") or {}).get("is_closed"))}, 200


def redmine_set_status(issue_id, status_id):
    """ステータスを変える。Redmine は許されていない変更を黙って無視するので、変えたあとに読み直して確かめる。"""
    try:
        redmine_call(f"/issues/{issue_id}.json", "PUT", {"issue": {"status_id": status_id}})
        now = (redmine_call(f"/issues/{issue_id}.json").get("issue", {}).get("status") or {})
    except Exception as e:
        return {"error": f"ステータスを変えられませんでした: {e}"}, 502
    redmine_cache["at"] = 0  # 次の一覧で取り直す
    focus_forget(str(issue_id))  # 対応中・吹き出しの Redmine の情報もすぐ取り直す
    if now.get("id") != status_id:
        return {"error": f"Redmine が変更を受け付けませんでした（今は「{now.get('name', '?')}」のまま）"}, 409
    return {"ok": True, "status": now.get("name", "")}, 200


link_title_cache = {}  # URL -> (タイトル, 取った時刻)。1 日覚える

# ---- アーティファクトの題名 ----
# claude.ai のアーティファクトはログインしないと題名が見えない。Claude の記録に残る公開の結果
# （「Published <ファイル> at https://claude.ai/artifact/<id>」）から元のファイルを引き、その <title> と説明を使う
ARTIFACT_FILE = os.path.join(CACHE, "artifact_titles.json")
ARTIFACT_PUB = re.compile(r"Published (\S+?) at https://claude\.ai/(?:code/)?artifact/([\w-]+)")
artifact_lock = threading.Lock()
artifacts = {"files": {}, "ids": {}}  # files: 記録のパス -> 見終えた大きさ / ids: id -> {"title", "desc", "path"}


def artifact_title_of(path, fallback=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(200_000)
        t = re.search(r"<title[^>]*>(.*?)</title>", head, re.S | re.I)
        if t and t.group(1).strip():
            return html.unescape(re.sub(r"\s+", " ", t.group(1))).strip()
        h = re.search(r"^#\s+(.+)$", head, re.M)  # Markdown なら最初の見出し
        if h:
            return h.group(1).strip()
    except OSError:
        pass
    return fallback or os.path.splitext(os.path.basename(path))[0]


def load_artifacts():
    """前回までに集めた題名を読む（起動直後の題名の問い合わせに、記録を探し終える前から答えられるように）。"""
    with artifact_lock:
        try:
            with open(ARTIFACT_FILE, encoding="utf-8") as f:
                artifacts.update(json.load(f))
        except (OSError, ValueError):
            pass


def scan_artifacts():
    """アーティファクトを公開した記録を探して id -> 題名を作る。記録は前回読んだところから先だけ読む。

    読んでいる間は artifact_lock を持たない（題名の問い合わせを待たせない）。見つけた分だけ、最後にまとめて足す。
    """
    try:  # 全部を Python で読むと遅いので、公開の結果を含む記録だけ grep で絞る
        out = subprocess.run(["grep", "-rlE", "--include=*.jsonl", r"Published [^ ]+ at https://claude\.ai/", os.path.join(HOME, ".claude", "projects")],
                             capture_output=True, text=True, timeout=120).stdout.split("\n")
    except (OSError, subprocess.TimeoutExpired):
        return
    with artifact_lock:
        seen = dict(artifacts["files"])
    found, sizes = [], {}  # found: (id, 公開したファイル, 説明)
    for path in filter(None, out):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        prev = seen.get(path, 0)
        if prev == size:
            continue
        descs = {}  # 公開したファイル -> Artifact を呼んだときの説明
        try:
            with open(path, "rb") as f:
                f.seek(prev if prev < size else 0)
                for raw in f:
                    line = raw.decode("utf-8", "replace")
                    if '"Artifact"' in line and '"description"' in line:
                        try:
                            for b in json.loads(line).get("message", {}).get("content") or []:
                                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Artifact":
                                    inp = b.get("input") or {}
                                    if inp.get("file_path") and inp.get("description"):
                                        descs[inp["file_path"]] = inp["description"]
                        except ValueError:
                            pass
                    if "Published " not in line:
                        continue
                    for fp, aid in ARTIFACT_PUB.findall(line.replace("\\n", "\n")):
                        fp = fp.replace("\\/", "/")
                        found.append((aid, fp, descs.get(fp, "")))
        except OSError:
            continue
        sizes[path] = size
    if not sizes:
        return
    titles = {fp: artifact_title_of(fp, "") for _, fp, _ in found}  # ファイルを読むのも lock の外で
    with artifact_lock:
        for aid, fp, desc in found:  # 同じ id を出し直したときは、あとのほうで上書きする（題名を変えて出し直すことがある）
            old = artifacts["ids"].get(aid) or {}
            artifacts["ids"][aid] = {"title": titles[fp] if os.path.exists(fp) else (old.get("title") or titles[fp]),
                                     "desc": desc or old.get("desc", ""), "path": fp}
        artifacts["files"].update(sizes)
        data = json.dumps(artifacts, ensure_ascii=False)
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(ARTIFACT_FILE + ".tmp", "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(ARTIFACT_FILE + ".tmp", ARTIFACT_FILE)
    except OSError:
        pass


def artifacts_loop():
    while True:
        try:
            scan_artifacts()
        except Exception as e:
            print(f"{time.strftime('%F %T')} アーティファクトの題名を集められませんでした: {e}", file=sys.stderr, flush=True)
        time.sleep(300)


def link_title(url):
    """メモ・リンク一覧の URL のページのタイトル（リンクの文字にし、マウスを乗せると説明と URL を出す）。

    メモ・リンク一覧にある URL だけを引く（ほかの URL をこの Mac から取りに行かせない）。
    GitHub の PR・issue は gh、Redmine のチケットは API、Redmine の Wiki は URL のページ名、それ以外はページの <title>。
    """
    with links_lock:
        in_links = url in links
    if not re.fullmatch(r"https?://\S+", url) or not (in_links or url in memo_read()["text"]):
        return {"error": "メモ・リンク一覧に無い URL です"}, 403
    a = re.match(r"https://claude\.ai/(?:code/)?artifact/([\w-]+)", url)
    if a:  # アーティファクトは公開した記録から（見つからなければ題名なし）。記録は 5 分ごとに読み直すので覚えない
        with artifact_lock:
            hit = artifacts["ids"].get(a.group(1))
        return {"title": hit["title"] if hit else "", "desc": hit["desc"] if hit else ""}, 200
    hit = link_title_cache.get(url)
    if hit and time.time() - hit[1] < 86400:
        return {"title": hit[0]}, 200
    title = ""
    host, _ = redmine_creds()
    try:
        m = re.match(r"https://github\.com/([\w.-]+)/([\w.-]+)/(?:pull|issues)/(\d+)", url)
        r = re.match(re.escape(host) + r"/issues/(\d+)", url) if host else None
        w = re.match(re.escape(host) + r"/projects/[^/]+/wiki/([^?#]+)", url) if host else None
        if m:
            gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
            out = subprocess.run([gh, "api", f"repos/{m.group(1)}/{m.group(2)}/issues/{m.group(3)}", "--jq", ".title"],
                                 capture_output=True, text=True, timeout=15)
            if out.returncode == 0:
                title = f"{m.group(2)}#{m.group(3)}: {out.stdout.strip()}"
        elif r:
            i = redmine_call(f"/issues/{r.group(1)}.json").get("issue", {})
            title = f"#{r.group(1)}: {i.get('subject', '')}"
        elif w:
            title = "Wiki: " + urllib.parse.unquote(w.group(1)).replace("_", " ")
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (dev-dashboard)", "Accept-Language": "ja"})
            with urllib.request.urlopen(req, timeout=8) as res:
                if "html" in (res.headers.get("Content-Type") or ""):
                    body = res.read(300_000).decode(res.headers.get_content_charset() or "utf-8", "replace")
                    t = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
                    title = html.unescape(re.sub(r"\s+", " ", t.group(1))).strip() if t else ""
                    if title == "Claude Artifact":  # アーティファクトはログインしないと本当の題名が出ない。どれも同じ題名なので出さない
                        title = ""
    except Exception as e:
        # 取れなかった URL も 1 時間は覚える（画面に出ている URL はまとめて引くので、毎回取りに行かないように）
        link_title_cache[url] = ("", time.time() - 86400 + 3600)
        return {"error": f"タイトルを取れませんでした: {e}"}, 200
    link_title_cache[url] = (title[:200], time.time())
    return {"title": title[:200]}, 200


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
    # ウォッチ中のチケット（担当分に無いもの）。担当分と違い、終了・解決・却下以外のステータスは全部出す（2026-11-25 ユーザー指定）。
    # Redmine の「未完了」には「解決」が入る（is_closed が付いていない）ので名前で除く。プロジェクトは絞らない
    try:
        seen = {i["id"] for i in issues}
        issues += [{**i, "watch": True} for i in get("/issues.json?watcher_id=me&status_id=open&sort=updated_on:desc&limit=100&include=relations")
                   if i["id"] not in seen and (i.get("status") or {}).get("name") not in REDMINE_WATCH_EXCLUDE]
    except Exception:
        pass  # ウォッチが取れなくても担当分は出す
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
         "assignee": (i.get("assigned_to") or {}).get("name", ""), "watch": bool(i.get("watch")), "last": journal_last(i["id"]),
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
                out = subprocess.run(["git", "-C", path, "for-each-ref", "--format=%(refname) %(objectname) %(committerdate:unix)",
                                      "refs/heads", "refs/remotes/origin"], capture_output=True, text=True, timeout=5).stdout
            except (OSError, subprocess.TimeoutExpired):
                continue
            heads, remotes = {}, {}
            ts = {}
            for line in out.splitlines():
                ref, sha, t = (line.split(" ") + ["", ""])[:3]
                if ref.startswith("refs/heads/"):
                    heads[ref[len("refs/heads/"):]] = sha
                    ts[ref[len("refs/heads/"):]] = int(t) if t.isdigit() else 0
                elif ref.startswith("refs/remotes/origin/"):
                    remotes[ref[len("refs/remotes/origin/"):]] = sha
            current = branch_of(path)
            for b, sha in heads.items():
                for n in set(TICKET.findall(b)):
                    entry = {"env": env, "repo": repo, "branch": b, "current": b == current, "ts": ts.get(b, 0)}
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


review_cache = {"at": 0, "mine": {}, "requested": []}  # mine: (リポジトリ, ブランチ) -> レビュー状況 / requested: 自分が reviewer の PR


def refresh_reviews():
    """自分のオープンな PR のレビュー状況と、自分がレビューを頼まれている PR（ticket_v2 / ticket_v2_api だけ）を取る。"""
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    mine, ok = {}, True
    for repo in REPO_NAMES:
        try:
            out = subprocess.run([gh, "pr", "list", "--repo", f"{GH_OWNER}/{repo}", "--author", "@me", "--state", "open", "--limit", "100",
                                  "--json", "number,headRefName,reviewDecision,reviewRequests,latestReviews"],
                                 capture_output=True, text=True, timeout=30)
            rows = json.loads(out.stdout) if out.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            rows = None
        if rows is None:
            ok = False
            continue
        for r in rows:
            mine[(repo, r["headRefName"])] = {
                "decision": r.get("reviewDecision") or "",
                "requests": [q.get("login") or q.get("name") or q.get("slug") or "" for q in r.get("reviewRequests") or []],
                "reviews": [{"who": (v.get("author") or {}).get("login", ""), "state": v.get("state", ""), "at": v.get("submittedAt", "")}
                            for v in r.get("latestReviews") or []]}
    try:
        out = subprocess.run([gh, "search", "prs", "--review-requested=@me", "--state=open", *[a for repo in REPO_NAMES for a in ("--repo", f"{GH_OWNER}/{repo}")],
                              "--json", "number,title,repository,url,author,updatedAt", "--limit", "50"],
                             capture_output=True, text=True, timeout=30)
        rows = json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        rows = None
    requested = []
    for r in rows or []:
        m = TICKET.search(r.get("title", ""))
        if m:
            requested.append({"ticket": m.group(1), "repo": (r.get("repository") or {}).get("name", ""), "number": r["number"], "url": r["url"],
                              "title": r.get("title", ""), "author": (r.get("author") or {}).get("login", ""), "updated": r.get("updatedAt", "")})
    with pr_lock:
        if ok:
            review_cache["mine"] = mine
        else:
            review_cache["mine"].update(mine)
        if rows is not None:
            review_cache["requested"] = requested
        review_cache["at"] = time.time()


def pr_loop():
    while True:
        try:
            refresh_prs()
        except Exception as e:
            print(f"{time.strftime('%F %T')} PR の取得に失敗: {e}", file=sys.stderr, flush=True)
        try:
            refresh_reviews()
        except Exception as e:
            print(f"{time.strftime('%F %T')} PR のレビュー状況の取得に失敗: {e}", file=sys.stderr, flush=True)
        time.sleep(300)


def branch_of(repo):
    """リポジトリの今のブランチ名（.git/HEAD を読むだけ。取れなければ \"\"）。"""
    try:
        with open(os.path.join(repo, ".git", "HEAD")) as f:
            ref = f.read().strip()
    except OSError:
        return ""
    return ref.removeprefix("ref: refs/heads/") if ref.startswith("ref: ") else ""


def latest_branches(branches):
    """同じリポジトリ・同じ名前のブランチが複数の環境にあるとき、最新の1つだけ残す（PR が重複して出るのを防ぐ）。

    最新 = 先頭コミットの時刻が新しいもの。同じなら、そのチケットのブランチ全体で一番新しいコミットを持つ環境を優先する
    （API は env1・フロントは env3 のように環境が分かれないように）。退避用の backup/ はそのまま残す。
    """
    env_ts = {}
    for b in branches:
        env_ts[b["env"]] = max(env_ts.get(b["env"], 0), b.get("ts", 0))
    best = {}
    for b in branches:
        if b["branch"].startswith("backup/"):
            continue
        k = (b["repo"], b["branch"])
        rank = (b.get("ts", 0), env_ts[b["env"]], b["current"])
        if k not in best or rank > best[k][0]:
            best[k] = (rank, b)
    keep = {id(v[1]) for v in best.values()}
    return [b for b in branches if b["branch"].startswith("backup/") or id(b) in keep]


def redmine_view():
    """担当チケットに、どの枠（セッション）・どの環境のブランチ・issue docs があるかを付ける。"""
    data = redmine_issues()
    if "error" in data:
        return data
    panes = ai_panes()
    sessions = {}
    for sl in panes.get("slots", []):
        for tk in sl.get("tickets") or ([sl["ticket"]] if sl.get("ticket") else []):
            sessions.setdefault(tk, []).append(
                {"slot": sl["slot"], "env": sl["env"], "kind": sl["kind"], "state": sl["state"], "skill": sl.get("skill", ""), "skill_done": sl.get("skill_done", False)})
    places = ticket_places()

    def item(i):
        n = str(i["id"])
        p = places.get(n, {"branches": [], "docs": []})
        with hist_lock:
            h = sorted(hist.get(n, {}).items(), key=lambda kv: -kv[1])
        with pr_lock:
            branches = [{**b, "pr": pr_cache["prs"].get((b["repo"], b["branch"]))} for b in latest_branches(p["branches"])]
        return {"relations": [], **i, "url": f"{data['host']}/issues/{n}", "sessions": sessions.get(n, []),
                "branches": branches, "docs": sorted(set(p["docs"])),
                "history": [{"env": e, "last": t} for e, t in h]}

    items = [item(i) for i in data["issues"] if not i.get("watch")]
    watched = [item(i) for i in data["issues"] if i.get("watch")]  # ウォッチ分は担当分の後ろ（更新の新しい順のまま）
    tv = today_view()

    # 並び: ① tmux の枠で作業しているもの → ② 今日（朝 4:00 以降）作業したもの（最後に作業した時刻の新しい順）
    #       → ③ それ以外。①③ の中の並び（優先度の高い順 → 更新の新しい順）は変えない（sort は安定）
    def order(x):
        if x["sessions"]:
            return (0, 0)
        t = tv["tickets"].get(str(x["id"]))
        return (1, -t["last"]) if t else (2, 0)
    items.sort(key=order)
    mine_count = len(items)
    items += watched
    mine = {str(i["id"]) for i in data["issues"]}  # 担当分＋ウォッチ分（下の「担当外・完了済み」に重ねて出さない）
    host, key = redmine_creds()
    extra = [{**item(i), "extra": True} for i in today_extra_issues(set(tv["tickets"]) - mine, host, key)]
    # ④ 担当一覧に無い（担当外・完了済み）が、直近 HIST_DAYS 日に作業したチケット。一覧のいちばん下に、最後に作業した時刻の新しい順で置く
    #    話に出ただけの番号まで含めると数百件になるので、セッションの作業番号だったものだけ（hist_work）
    with hist_lock:
        recent_last = dict(hist_work)
    for n, t in tv["tickets"].items():
        recent_last[n] = max(recent_last.get(n, 0), t["last"])
    recent_ids = set(recent_last) - mine
    recent = [{**item(i), "extra": True, "recent": True} for i in today_extra_issues(recent_ids, host, key, recent_cache)
              if i["status"]]  # Redmine に無い番号（チケットではない数字）は出さない
    recent.sort(key=lambda x: -recent_last.get(str(x["id"]), 0))
    items += recent
    # ⑤ メモの見出し（「#番号 … -----」）の番号で、ここまでに無いもの（担当外で最近触っていない等）。メモの見出しの進捗用で、一覧には出さない
    listed = mine | {str(i["id"]) for i in extra + recent}
    memo_ids = {str(int(n)) for n in MEMO_HEAD_TICKET.findall(memo_read()["text"])} - listed
    memo_extra = [{**item(i), "extra": True} for i in today_extra_issues(memo_ids, host, key, memo_cache) if i["status"]]
    return {"fetched_at": data["fetched_at"], "issues": items, "mine_count": mine_count, "watch_count": len(watched), "history_days": HIST_DAYS, "pr_at": pr_cache["at"],
            "today": tv, "today_extra": extra, "memo_extra": memo_extra}


# ---- ヘッダーの「対応中」: tmux の枠のチケットと、レビューを頼まれている PR のチケット。段階と担当（誰の番か）を付ける ----
FOCUS_STAGES = ["", "設計", "実装", "レビュー", "PR", "testing", "staging", "本番", "完了"]
FOCUS_DESIGN = re.compile(r"ct-(analyze|architect|planner|bug-|sweep|scope|grill|paltera|issue-(auto|docs))")
FOCUS_REVIEW = re.compile(r"ct-(verify|review|code-review|security-review|finish|issue-reconcile|pr-create|pr-turn)")
# 自分の最新コメントが「質問」か（報告・連絡は質問にしない）。引用（> の行）は除いて見る
FOCUS_QUESTION = re.compile(r"[?？]|でしょうか|ですか|ますか|ませんか|教えて(ください|いただ)|ご判断|ご意見|いかがでしょう")
focus_lock = threading.Lock()
focus_rm = {}      # チケット番号 -> (取った時刻, Redmine の詳細)
focus_merge = {}   # チケット番号 -> (取った時刻, {"develop", "release", "master"})
redmine_me = {"id": None}


def focus_forget(n):
    """そのチケットの覚えている Redmine の情報と、取り込み先（develop / release / master）の確認結果を捨てる。"""
    with focus_lock:
        focus_rm.pop(n, None)
        focus_merge.pop(n, None)


def refresh_branch_prs(brs):
    """ブランチの PR とレビュー状況を、そのブランチだけ GitHub から取り直す（吹き出しの ↻ 用。5 分ごとの一括取得を待たない）。"""
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    for b in brs:
        try:
            out = subprocess.run([gh, "pr", "list", "--repo", f"{GH_OWNER}/{b['repo']}", "--head", b["branch"], "--author", "@me", "--state", "all",
                                  "--limit", "1", "--json", "number,state,isDraft,url,reviewDecision,reviewRequests,latestReviews"],
                                 capture_output=True, text=True, timeout=20)
            rows = json.loads(out.stdout) if out.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            rows = None
        if not rows:
            continue
        r, k = rows[0], (b["repo"], b["branch"])
        with pr_lock:
            pr_cache["prs"][k] = {"number": r["number"], "state": r["state"].lower(), "draft": r.get("isDraft", False), "url": r["url"]}
            if r["state"] == "OPEN":
                review_cache["mine"][k] = {
                    "decision": r.get("reviewDecision") or "",
                    "requests": [q.get("login") or q.get("name") or q.get("slug") or "" for q in r.get("reviewRequests") or []],
                    "reviews": [{"who": (v.get("author") or {}).get("login", ""), "state": v.get("state", ""), "at": v.get("submittedAt", "")}
                                for v in r.get("latestReviews") or []]}
            else:
                review_cache["mine"].pop(k, None)


def redmine_my_id():
    if redmine_me["id"] is None:
        try:
            redmine_me["id"] = redmine_call("/users/current.json").get("user", {}).get("id")
        except Exception:
            return None
    return redmine_me["id"]


def focus_issue(n):
    """チケットの件名・ステータス・担当・最新コメント・担当の付け替え。3 分覚える。"""
    with focus_lock:
        c = focus_rm.get(n)
    if c and time.time() - c[0] < 180:
        return c[1]
    try:
        i = redmine_call(f"/issues/{n}.json?include=journals,relations").get("issue", {})
    except Exception:
        return c[1] if c else None
    js = i.get("journals") or []
    notes = [j for j in js if (j.get("notes") or "").strip()]
    last = notes[-1] if notes else None
    assign = next((j for j in reversed(js) if any(d.get("name") == "assigned_to_id" for d in j.get("details") or [])), None)
    st = i.get("status") or {}
    waits = []
    for r in i.get("relations") or []:
        t, me = r["relation_type"], i.get("id")
        if (t in ("blocks", "precedes") and r["issue_to_id"] == me) or (t in ("blocked", "follows") and r["issue_id"] == me):
            waits.append(r["issue_id"] if r["issue_to_id"] == me else r["issue_to_id"])
    open_waits = []
    if waits:
        try:
            for o in redmine_call(f"/issues.json?issue_id={','.join(map(str, waits))}&status_id=*&limit=100").get("issues", []):
                ost = o.get("status") or {}
                if not (ost.get("is_closed") or o.get("closed_on")):
                    open_waits.append(o["id"])
        except Exception:
            open_waits = waits
    d = {"subject": i.get("subject", ""), "status": st.get("name", ""), "closed": bool(st.get("is_closed")) or bool(i.get("closed_on")),
         "priority": (i.get("priority") or {}).get("name", ""),
         "assignee": (i.get("assigned_to") or {}).get("name", ""), "assignee_id": (i.get("assigned_to") or {}).get("id"),
         "last_note": {"who": last["user"]["name"], "who_id": last["user"]["id"], "at": last["created_on"],
                       "text": re.sub(r"\s+", " ", last["notes"]).strip()[:120],
                       "question": bool(FOCUS_QUESTION.search(re.sub(r"(?m)^>.*$", "", last["notes"])))} if last else None,
         "assigned_at": assign["created_on"] if assign else "", "waits": open_waits}
    with focus_lock:
        focus_rm[n] = (time.time(), d)
    return d


def freshest_repo(repo):
    """git fetch がいちばん新しい環境の作業ツリー（origin/* を見るため）。"""
    best, t = None, -1
    for d in ENV_DIRS:
        path = os.path.join(HOME, "www", d, repo)
        try:
            m = os.path.getmtime(os.path.join(path, ".git", "FETCH_HEAD"))
        except OSError:
            continue
        if m > t:
            best, t = path, m
    return best


def focus_merged(n):
    """origin の develop / release / master に、このチケットのコミット（「#番号」か「feature/番号」）が入っているか。10 分覚える。"""
    with focus_lock:
        c = focus_merge.get(n)
    if c and time.time() - c[0] < 600:
        return c[1]
    res = {"develop": False, "release": False, "master": False}
    for repo in REPO_NAMES:
        path = freshest_repo(repo)
        if not path:
            continue
        for ref in res:
            if res[ref]:
                continue
            try:
                out = subprocess.run(["git", "-C", path, "log", f"origin/{ref}", "--since=1.year", "-E", f"--grep=(#|feature/){n}([^0-9]|$)",
                                      "-1", "--format=%h"], capture_output=True, text=True, timeout=10).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                out = ""
            res[ref] = bool(out)
    with focus_lock:
        focus_merge[n] = (time.time(), res)
    return res


def focus_phase(n):
    """issue docs の 03_progress.md の「### Phase」ごとのチェックで、終わったフェーズ数 / 全フェーズ数。2 フェーズ未満なら None。"""
    files = []
    for d in ENV_DIRS:
        files += glob.glob(os.path.join(HOME, "www", d, "docs", "issues", "active", f"{n}_*", "03_progress.md"))
    if not files:
        return None
    try:
        text = open(max(files, key=os.path.getmtime), encoding="utf-8").read()
    except OSError:
        return None
    phases = re.split(r"(?m)^#{2,4}\s*(?:Phase|フェーズ)\s*\S*", text)[1:]
    boxes = [re.findall(r"(?m)^\s*[-*] \[([ xX])\]", ph) for ph in phases]
    boxes = [b for b in boxes if b]
    if len(boxes) < 2:
        return None
    return {"done": sum(all(x.lower() == "x" for x in b) for b in boxes), "total": len(boxes)}


def local_hm(iso):
    """Redmine の UTC の日時（2026-11-17T07:11:00Z）を、手元の時刻の「11/17 16:11」にする。"""
    try:
        t = datetime.datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc).astimezone()
        return t.strftime("%m/%d %H:%M")
    except (ValueError, TypeError):
        return iso


def last_env(sess, envs, brs):
    """最後に作業した環境の番号（"1"〜"4"）。tmux の枠が開いていればその環境（処理中・確認待ちの枠を優先）。"""
    rank = {"wait": 3, "busy": 2, "idle": 1}
    if sess:
        return max(sess, key=lambda x: rank.get(x["state"], 0))["env"].removeprefix("env")
    strict = [x for x in envs if x["strict"]]
    if strict:
        return max(strict, key=lambda x: x["last"])["env"].removeprefix("env")
    return max(brs, key=lambda b: b.get("ts", 0))["env"].removeprefix("env") if brs else ""


def focus_view(only=None, fresh=False):
    """ヘッダーに出す「対応中」のチケット。tmux の枠の番号（複数番号も）＋レビューを頼まれている PR の番号。

    only を渡すと、そのチケット 1 件だけを同じ形で返す（Redmine 欄・メモの見出しにマウスを乗せたとき用）。
    fresh を付けると、そのチケットの Redmine・PR・取り込み先を覚えている分を使わずに取り直す（吹き出しの ↻）。
    """
    if only and fresh:
        focus_forget(only)
        p0 = ticket_places().get(only, {"branches": []})
        refresh_branch_prs([b for b in latest_branches(p0["branches"]) if not b["branch"].startswith("backup/")])
    panes = ai_panes()
    order, sessions = [], {}
    for sl in panes.get("slots", []):
        if sl["state"] == "stopped":
            continue
        for tk in sl.get("tickets") or ([sl["ticket"]] if sl.get("ticket") else []):
            if tk not in sessions:
                order.append(tk)
            sessions.setdefault(tk, []).append({"slot": sl["slot"], "env": sl["env"], "kind": sl["kind"], "state": sl["state"],
                                                "skill": sl.get("skill", ""), "skill_done": sl.get("skill_done", False)})
    with pr_lock:
        requested = list(review_cache["requested"])
        reviews = dict(review_cache["mine"])
        prs = dict(pr_cache["prs"])
    req_by = {}
    for r in requested:
        req_by.setdefault(r["ticket"], []).append(r)
        if r["ticket"] not in order:
            order.append(r["ticket"])
    # tmux を閉じても、今日（朝 4:00 以降）作業したチケットは残す
    tv = {n: t for n, t in today_view()["tickets"].items() if t["work"] or n in sessions or n in req_by}
    for n in tv:
        if n not in order:
            order.append(n)
    # 並び: 最後に作業した時刻の新しい順。tmux の枠で動いているものは今、レビュー依頼だけのものは PR の更新時刻
    now = time.time()

    def last_of(n):
        t = tv.get(n, {}).get("work_last", 0)
        if sessions.get(n):
            t = now
        for r in req_by.get(n, []):
            try:
                t = max(t, datetime.datetime.fromisoformat(r["updated"].replace("Z", "+00:00")).timestamp())
            except (ValueError, KeyError):
                pass
        return t
    if only:
        order = [only]
        tv = {k: t for k, t in today_view()["tickets"].items() if k == only}
    else:
        last = {n: last_of(n) for n in order}
        order.sort(key=lambda n: -last[n])
    places = ticket_places()
    me = redmine_my_id()
    host, _ = redmine_creds()
    items = []
    for n in order:
        rm = focus_issue(n) or {}
        p = places.get(n, {"branches": [], "docs": []})
        brs = [b for b in latest_branches(p["branches"]) if not b["branch"].startswith("backup/")]
        mypr = []
        for b in brs:
            pr = prs.get((b["repo"], b["branch"]))
            if pr:
                mypr.append({**pr, "repo": b["repo"], **reviews.get((b["repo"], b["branch"]), {})})
        merged = focus_merged(n) if brs or mypr else {"develop": False, "release": False, "master": False}
        skills = " ".join(x["skill"] for x in sessions.get(n, []))
        stage, why = 0, ""
        for cond, k, w in [
            (bool(p["docs"]) or bool(FOCUS_DESIGN.search(skills)), 1, "issue docs あり／調査・設計のスキル"),
            (bool(brs), 2, "ブランチあり"),
            (bool(FOCUS_REVIEW.search(skills)), 3, "レビュー系のスキルを実行"),
            (any(x["state"] == "open" for x in mypr), 4, "PR がオープン"),
            (merged["develop"], 5, "develop に取り込み済み"),
            (merged["release"] or any(x["state"] == "merged" for x in mypr), 6, "release に取り込み済み"),
            (merged["master"], 7, "master に取り込み済み"),
            (bool(rm.get("closed")), 8, f"Redmine が {rm.get('status', '')}")]:
            if cond and k >= stage:
                stage, why = k, w
        # 担当（誰の番か）: 上から順に当てはめる
        opens = [x for x in mypr if x["state"] == "open" and not x.get("draft")]
        ln = rm.get("last_note")
        if n in req_by:
            r = req_by[n][0]
            ball = ("review_in", "📨 レビュー依頼が来てる", f"{r['repo']}#{r['number']}（{r['author']}）で reviewer に指定されている")
        elif any(x.get("decision") == "CHANGES_REQUESTED" for x in opens):
            x = next(x for x in opens if x.get("decision") == "CHANGES_REQUESTED")
            ball = ("fix", "✍️ 修正依頼あり", f"{x['repo']}#{x['number']} が「変更を求める」")
        elif opens and any(x.get("requests") or x.get("decision") == "REVIEW_REQUIRED" for x in opens) \
                and not all(x.get("decision") == "APPROVED" for x in opens):
            who = sorted({w for x in opens for w in x.get("requests") or []})
            ball = ("reviewing", "👀 レビュー依頼中", f"レビュー待ち: {', '.join(who) or '未承認'}")
        elif opens and all(x.get("decision") == "APPROVED" for x in opens):
            ball = ("approved", "✅ 承認済み", "オープンな PR がすべて承認済み（デプロイ待ち）")
        elif rm.get("closed"):
            ball = ("done", "完了", f"Redmine が {rm.get('status', '')}")
        elif rm.get("waits"):
            ball = ("wait", "⏳ 他チケット待ち", "先行・ブロックのチケットが未完了: " + ", ".join(f"#{w}" for w in rm["waits"]))
        elif me and rm.get("assignee_id") and rm["assignee_id"] != me and ln and ln["who_id"] == me and ln.get("question"):
            ball = ("asking", "🙋 質問中", f"担当 {rm['assignee']}・最新コメントが自分の質問（{local_hm(ln['at'])}）")
        elif me and rm.get("assignee_id") and rm["assignee_id"] != me:
            mine_last = ln and ln["who_id"] == me
            ball = ("other", f"👤 {rm['assignee']} の番",
                    f"Redmine の担当が {rm['assignee']}" + (f"・最新コメントは自分の報告（{local_hm(ln['at'])}。質問の言い回しなし）" if mine_last else ""))
        else:
            reason = "Redmine の担当が自分"
            if ln and me and ln["who_id"] != me:
                reason += f"・最新コメントは {ln['who']}（{local_hm(ln['at'])}）"
            ball = ("mine", "🔴 自分の番", reason)
        items.append({"id": n, "subject": rm.get("subject", "") or (req_by.get(n, [{}])[0].get("title", "")), "url": f"{host}/issues/{n}" if host else "",
                      "status": rm.get("status", ""), "priority": rm.get("priority", ""), "assignee": rm.get("assignee", ""),
                      "last_note": ln, "stage": stage, "stage_label": FOCUS_STAGES[stage], "stage_why": why, "phase": focus_phase(n),
                      "ball": {"kind": ball[0], "label": ball[1], "why": ball[2]}, "sessions": sessions.get(n, []),
                      "last": tv.get(n, {}).get("work_last", 0), "today": n in tv,
                      # 最後に作業した環境の番号（tmux の枠 → 今日作業として扱った入力の最後 → いちばん新しいブランチの順に探す）
                      "env": last_env(sessions.get(n, []), tv.get(n, {}).get("envs", []), brs),
                      "branches": [{"env": b["env"], "repo": b["repo"], "branch": b["branch"]} for b in brs],
                      "prs": mypr, "review_requested": req_by.get(n, []),
                      **ticket_links(n, {p.get("url", "") for p in mypr} | {r.get("url", "") for r in req_by.get(n, [])})})
    return {"items": items, "pr_at": review_cache["at"]}


PR_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
ARTIFACT_ID = re.compile(r"^https://claude\.ai/(?:code/)?artifact/([\w-]+)")
TICKET_LINKS_MAX = 8


def ticket_links(n, shown):
    """会話ログのリンク一覧から、そのチケットのアーティファクトと PR の URL（新しい順）。吹き出しに出す。
    shown: 吹き出しの PR・レビュー依頼の行に既に出ている PR の URL（重ねて出さない）。"""
    with links_lock:
        vs = sorted((v for v in links.values() if v.get("ticket") == n), key=lambda v: -v["ts"])
    arts, prs, seen = [], [], set(shown)
    for v in vs:
        a, p = ARTIFACT_ID.match(v["url"]), PR_URL.match(v["url"])
        if a and len(arts) < TICKET_LINKS_MAX and a.group(1) not in seen:
            seen.add(a.group(1))
            with artifact_lock:
                info = artifacts["ids"].get(a.group(1)) or {}
            arts.append({"url": v["url"], "title": info.get("title", ""), "ts": v["ts"]})
        elif p and len(prs) < TICKET_LINKS_MAX:
            url = p.group(0)  # /files・#discussion などは PR の URL にまとめる
            if url in seen:
                continue
            seen.add(url)
            prs.append({"url": url, "repo": p.group(2), "number": int(p.group(3)), "ts": v["ts"]})
    return {"artifacts": arts, "pr_links": prs}


HIST_DAYS = 30
hist_lock = threading.Lock()
hist = {}        # チケット番号 -> {env: 最後に扱った時刻}（直近 HIST_DAYS 日、ユーザーが入力した文だけ）
hist_work = {}   # チケット番号 -> 最後に「作業の番号」だった時刻（直近 HIST_DAYS 日。話に出ただけの番号は入れない）
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


def history_entries(path, kind, st, lines, work=None):
    """記録の行から (チケット番号, 環境, 時刻) を出す。env1〜env4 の作業フォルダのセッションだけ。

    work（辞書）を渡すと、その入力の作業番号（session_ticket。話に出ただけの番号は含まない）-> 最後の時刻 も書き込む。
    """
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
        if work is not None:
            wt = session_ticket(text, claude_work_ticket(d) if kind == "claude" else work_ticket(text))
            if wt:
                work[wt] = max(work.get(wt, 0), ts)
        for n in set(MENTION_TICKET.findall(text)):
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
        work = {}
        found = list(history_entries(path, kind, st, lines, work))
        with hist_lock:
            for n, env, ts, _ in found:
                cur = hist.setdefault(n, {})
                cur[env] = max(cur.get(env, 0), ts)
            for n, ts in work.items():
                hist_work[n] = max(hist_work.get(n, 0), ts)
    limit = time.time() - HIST_DAYS * 86400
    with hist_lock:
        for n in [n for n, ts in hist_work.items() if ts < limit]:
            del hist_work[n]
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


# --- 今日の作業（Redmine 欄の「今日作業した」） ---------------------------------------------
# 「今日」は朝 4:00 で区切る（0:00〜3:59 は前の日の続き）。1 分ごとに、今日更新された Claude・Codex の記録を
# 追記分だけ読み、セッションごとに「いま作業しているチケット」を追って、その番号に作業した時間帯と入力した文を付ける。
DAY_START_HOUR = 4
TODAY_PROMPTS = 8          # 1 チケット・1 環境あたり残す入力の数（新しいものから）
TODAY_SNIPPET = 90         # 入力の冒頭として残す文字数
TS_FIELD = re.compile(r'"timestamp"\s*:\s*"([^"]+)"')
today_lock = threading.Lock()
today = {"start": 0, "files": {}, "work": {}, "commits": {}, "commits_at": 0, "mins": {}}
TS_GAP_MIN = 5  # 記録の間隔がこの分数以内なら、その間も作業していたとみなす（ct-timesheet と同じ）
extra_cache = {"at": 0, "ids": (), "issues": []}  # 今日作業した担当外・完了済みのチケット（5 分覚える）
memo_cache = {"at": 0, "ids": (), "issues": []}  # メモの見出しにある、ほかで引いていないチケット（5 分覚える）
# メモの見出しの行（「… -----」）の最初の #番号（画面と同じく ＃・全角数字も拾う。\d は全角数字にも当たるので int で半角にする）
MEMO_HEAD_TICKET = re.compile(r"^[ \t]*[^#\n]*?[#＃](\d{4,6})(?!\d)[^\n]*?-{3,}[ \t]*$", re.M)
recent_cache = {"at": 0, "ids": (), "issues": []}  # 直近 HIST_DAYS 日に扱った担当外・完了済みのチケット（5 分覚える）


def day_start(now=None):
    """今日の始まり（朝 4:00）の時刻。4:00 より前なら前の日の 4:00。"""
    t = time.localtime(now or time.time())
    start = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, DAY_START_HOUR, 0, 0, 0, 0, -1))
    return start - 86400 if t.tm_hour < DAY_START_HOUR else start


def snippet(text):
    text = re.sub(r"<pasted_content\b.*?</pasted_content[^>]*>", " [貼り付け] ", text or "", flags=re.S)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:TODAY_SNIPPET] + ("…" if len(text) > TODAY_SNIPPET else "")


def session_ticket(text, wt):
    """入力からセッションの作業番号を決める: work_ticket を優先し、無ければ 300 文字以内の入力の主な番号。"""
    if wt:
        return wt
    if text and len(text) <= 300 and "<pasted_content" not in text \
            and not text.lstrip().startswith("This session is being continued"):
        return main_ticket(text)
    return ""


def _today_touch(work, tk, env, ts, prompt=None, strict=False):
    w = work.setdefault(tk, {}).setdefault(env, {"first": ts, "last": ts, "prompts": []})
    # strict: 作業の番号と分かる入力（work_ticket）で決まった番号か。話に出ただけの番号（短い入力の主な番号）は False
    w["strict"] = w.get("strict", False) or strict
    w["first"], w["last"] = min(w["first"], ts), max(w["last"], ts)
    if prompt:
        w["prompts"] = (w["prompts"] + [{"ts": ts, "text": prompt}])[-TODAY_PROMPTS:]


# コマンドの書き出しが tmux-title のものだけ（Claude は Bash の command の先頭、Codex は JSON の引用符の直後）。スクリプトの中の文字列などは拾わない
TITLE_CMD = re.compile(r"(?:^\s*|(?<=\"))(?:\S*/)?tmux-title\s+(?:(ticket)\s+((?:#?1\d{4}(?!\d)[\s,]*)+)|(set)\s+[\\\"']*\s*((?:[#＃]1\d{4}(?!\d)[\s,]*)*)|(clear)\b)")


def title_cmd_tickets(line, kind):
    """その行が AI の実行した ~/bin/tmux-title なら、付けた番号の一覧（clear は []）。それ以外は None。

    スキルの説明（入力側に載る）の例文を拾わないよう、Claude は assistant の Bash の tool_use、Codex は function_call の行だけを見る。
    """
    if "tmux-title" not in line:
        return None
    if kind == "claude":
        if '"tool_use"' not in line or '"assistant"' not in line:
            return None
        try:
            items = (json.loads(line).get("message") or {}).get("content") or []
        except ValueError:
            return None
        cmds = [str((x.get("input") or {}).get("command", "")) for x in items
                if isinstance(x, dict) and x.get("type") == "tool_use" and x.get("name") == "Bash"]
    else:
        if '"function_call"' not in line:
            return None
        cmds = [line]
    found = None
    for cmd in cmds:
        for m in (TITLE_CMD.finditer(cmd) if kind != "claude" else [TITLE_CMD.match(cmd)] if TITLE_CMD.match(cmd) else []):
            found = [] if m.group(5) else list(dict.fromkeys(re.findall(r"1\d{4}", m.group(2) or m.group(4) or "")))
    return found


def scan_today_once():
    start = day_start()
    with today_lock:
        if today["start"] != start:  # 日が変わったら最初から
            today.update(start=start, files={}, work={}, commits={}, commits_at=0, mins={})
        files, work, mins = today["files"], today["work"], today["mins"]
    for path, kind in history_files():
        try:
            if os.path.getmtime(path) < start:
                continue
        except OSError:
            continue
        st = files.setdefault(path, {"offset": 0, "cwd": "", "cur": ""})
        try:
            lines = read_new_lines(path, st)
        except OSError:
            continue
        found = []  # (ticket, env, ts, prompt)
        ticks = []  # (分, ticket。作業番号が無ければ "")。日報の時間の下書き用
        for line in lines:
            m = TS_FIELD.search(line)
            ts = iso_ts(m.group(1)) if m else 0.0
            prompt, wt = None, ""
            if kind == "claude":
                if '"cwd"' in line and '"user"' in line and '"tool_use_id"' not in line:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        d = {}
                    st["cwd"] = d.get("cwd") or st["cwd"]
                    text = prompt_text(d)
                    if text and not d.get("isCompactSummary"):
                        prompt, wt = text, claude_work_ticket(d)
            else:
                if '"session_meta"' in line:
                    try:
                        st["cwd"] = json.loads(line).get("payload", {}).get("cwd", "") or st["cwd"]
                    except ValueError:
                        pass
                elif '"user"' in line:
                    try:
                        text = codex_prompt_text(json.loads(line).get("payload") or {})
                    except ValueError:
                        text = ""
                    if text:
                        prompt, wt = text, work_ticket(text)
            if prompt:
                new = session_ticket(prompt, wt)
                if new:
                    st["cur"], st["strict"] = new, bool(wt)
            # ct-tmux-title で枠に付けた番号は、以降の入力を全部その番号の作業として数える（番号を書かずに進めた作業も残すため）
            titled = title_cmd_tickets(line, kind)
            if titled is not None:
                st["label"] = titled if ts >= start else []  # 前の日に付けたタイトルは今日の作業に数えない
            env = env_of(st["cwd"])
            if ts >= start and env in ENV_DIRS.values():
                # 枠のタイトルに番号が複数あれば、その分は全部で等分する（空白区切りで持つ。timesheet_today で割る）
                ticks.append((int(ts // 60), " ".join(dict.fromkeys(([st["cur"]] if st["cur"] else []) + (st.get("label") or [])))))
            if ts >= start and st["cur"] and env in ENV_DIRS.values():
                found.append((st["cur"], env, ts, snippet(prompt) if prompt else None, st.get("strict", False)))
            if ts >= start and env in ENV_DIRS.values() and (prompt or titled):
                for tk in st.get("label") or []:
                    if tk != st["cur"]:
                        found.append((tk, env, ts, snippet(prompt) if prompt else None, True))
                    elif not st.get("strict"):
                        found.append((tk, env, ts, None, True))  # 番号は同じでも、話に出ただけの扱いを作業に上げる
        if found or ticks:
            with today_lock:
                m = mins.setdefault(path, {})
                for minute, tk in ticks:
                    m[minute] = tk or m.get(minute, "")
                for tk, env, ts, p, strict in found:
                    _today_touch(work, tk, env, ts, p, strict)
    if time.time() - today["commits_at"] >= 300:
        commits = today_commits(start)
        with today_lock:
            today.update(commits=commits, commits_at=time.time())


def today_commits(start):
    """今日の 4:00 以降の自分のコミット（refs #番号 を含むもの）。各環境で fetch した同じコミットは 1 件にまとめる。"""
    seen, out = set(), {}
    for d, env in ENV_DIRS.items():
        root = os.path.join(HOME, "www", d)
        for repo in ("", *REPO_NAMES):
            path = os.path.join(root, repo) if repo else root
            if not os.path.isdir(os.path.join(path, ".git")):
                continue
            try:
                me = subprocess.run(["git", "-C", path, "config", "user.email"], capture_output=True, text=True, timeout=5).stdout.strip()
                log = subprocess.run(["git", "-C", path, "log", "--all", f"--since=@{int(start)}", "--format=%H%x09%ct%x09%ae%x09%s"],
                                     capture_output=True, text=True, timeout=20).stdout.splitlines()
            except (OSError, subprocess.TimeoutExpired):
                continue
            for row in log:
                parts = row.split("\t", 3)
                if len(parts) < 4 or parts[0] in seen or (me and parts[2] != me):
                    continue
                for n in set(re.findall(r"#(1\d{4})(?!\d)", parts[3])):
                    seen.add(parts[0])
                    out.setdefault(n, []).append({"ts": int(parts[1]), "subject": parts[3][:120],
                                                  "where": f"{env} {repo or 'workspace'}"})
    return out


def today_loop():
    while True:
        try:
            scan_today_once()
        except Exception as e:  # 集め損ねても次の回でやり直す
            print(f"{time.strftime('%F %T')} 今日の作業の収集に失敗: {e}", file=sys.stderr, flush=True)
        time.sleep(60)


def today_view():
    """チケット番号 -> {"envs": [{env, first, last}], "prompts": [{ts, env, text}], "commits": [...], "last"}。"""
    with today_lock:
        work = json.loads(json.dumps(today["work"]))
        commits = dict(today["commits"])
        start = today["start"] or day_start()
    out = {}
    for n in (set(work) | set(commits)) - REDMINE_MISSING:
        envs = [{"env": e, "first": w["first"], "last": w["last"], "strict": w.get("strict", False)} for e, w in sorted(work.get(n, {}).items())]
        prompts = sorted(({"ts": p["ts"], "env": e, "text": p["text"]} for e, w in work.get(n, {}).items() for p in w["prompts"]),
                         key=lambda p: -p["ts"])[:TODAY_PROMPTS]
        cm = sorted(commits.get(n, []), key=lambda c: -c["ts"])
        last = max([x["last"] for x in envs] + [c["ts"] for c in cm] or [0])
        # work: 作業の番号として扱った入力かコミットがある（ヘッダーの「対応中」に残すのはこれだけ）
        out[n] = {"envs": envs, "prompts": prompts, "commits": cm, "last": last, "work": bool(cm) or any(x["strict"] for x in envs),
                  "work_last": max([x["last"] for x in envs if x["strict"]] + [c["ts"] for c in cm] or [0])}
    return {"start": start, "tickets": out}


def today_extra_issues(ids, host, key, cache=None):
    """担当一覧に無いチケット（担当外・完了済み）を番号で Redmine から引く。5 分覚える。

    cache を渡さなければ「今日作業した」用（extra_cache）。直近の履歴用は recent_cache を渡す。
    """
    extra_cache = cache if cache is not None else globals()["extra_cache"]
    ids = tuple(sorted(ids))
    if not ids:
        return []
    if extra_cache["ids"] == ids and time.time() - extra_cache["at"] < 300:
        return extra_cache["issues"]
    import urllib.request
    issues, ok = [], True
    for k in range(0, len(ids), 50):
        req = urllib.request.Request(f"{host}/issues.json?issue_id={','.join(ids[k:k + 50])}&status_id=*&limit=100",
                                     headers={"X-Redmine-API-Key": key})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                issues += json.load(r).get("issues", [])
        except Exception as e:  # 引けなくても番号だけは出す
            ok = False
            print(f"{time.strftime('%F %T')} 今日の作業のチケットを Redmine から取れませんでした: {e}", file=sys.stderr, flush=True)
    found = {i["id"] for i in issues}
    if ok:  # 問い合わせが通ったときだけ「無い番号」と決める（通信の失敗で消さない）
        REDMINE_MISSING.update(n for n in ids if int(n) not in found)
        REDMINE_MISSING.difference_update(str(i) for i in found)
    rows = [{"id": i["id"], "subject": i.get("subject", ""), "status": (i.get("status") or {}).get("name", ""),
             "priority": (i.get("priority") or {}).get("name", ""), "updated_on": i.get("updated_on", ""),
             "assignee": (i.get("assigned_to") or {}).get("name", ""),
             "closed": bool((i.get("status") or {}).get("is_closed")) or bool(i.get("closed_on"))} for i in issues]
    rows += [{"id": int(n), "subject": "（Redmine で見つかりません）", "status": "", "priority": "", "updated_on": "",
              "assignee": "", "closed": False} for n in ids if int(n) not in found and not ok]
    extra_cache.update(at=time.time(), ids=ids, issues=rows)
    return rows


def run_action(action, env, comp):
    # 出力に UTF-8 で読めない文字（途中で切れた全角など）があっても止まらないよう errors="replace" で読む。
    # 何が起きても最後に running を外す（外さないと「実行中」のまま固まり、ほかの起動・停止を受け付けなくなる）
    rc = 1
    try:
        proc = subprocess.Popen([LOCAL_SERVER, action, env, comp], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            with job_lock:
                job["output"] += line
        rc = proc.wait()
    except OSError as e:
        with job_lock:
            job["output"] += f"⚠️  起動できませんでした: {e}\n"
    except Exception as e:
        with job_lock:
            job["output"] += f"⚠️  途中で止まりました: {e}\n"
    finally:
        with job_lock:
            job.update(running=False, rc=rc, finished=time.time())


# --- 日報（HRMOS勤怠 p.ieyasu.co）-----------------------------------------------------------
# 公開 API ではなく、画面と同じフォームを送る。HRMOS 側の画面が変わると動かなくなる。
# 更新は、いまある行を全部（変えていない行はいまの値のまま）と、足す行を送る。送らなかった行は HRMOS 側で時間が 0:00 になる。行の削除は _destroy=1 で送る。メール送信はしない。
HRMOS_BASE = "https://p.ieyasu.co"
HRMOS_TOKEN = re.compile(r'name="authenticity_token"\s+value="([^"]+)"')
HRMOS_ROW = re.compile(r"daily_report\[reports_attributes\]\[(\d+)\]\[(\w+)\]")
HRMOS_ID_FIELDS = ("business_partner_id", "project_id", "service_large_category_id", "service_medium_category_id", "service_category_id")
HRMOS_TIME = re.compile(r"(\d{1,2}):(\d{2})")
hrmos_lock = threading.Lock()   # HRMOS とのやり取りは1つずつ（ログインし直しが重ならないように）
hrmos_opener = None             # ログイン中の cookie を持つ
hrmos_ids = {}                  # (年, 月) -> {日: 日報 ID}


def timesheet_today():
    """今日（朝 4:00 以降）のチケット別の作業時間（分）。ct-timesheet スキルと同じ決め方:

    記録の間隔が TS_GAP_MIN 分以内ならその間も作業中とみなし、1分ごとに、同じ分に動いていたセッションの数で等分する
    （並行作業で水増ししない）。Claude・Codex を触っていない時間（ブラウザ確認・打ち合わせ）は入らない。
    """
    with today_lock:
        mins = [dict(m) for m in today.get("mins", {}).values()]
    per_min = {}
    for m in mins:
        keys = sorted(m)
        for i, k in enumerate(keys):
            per_min.setdefault(k, []).append(m[k])
            if i + 1 < len(keys) and keys[i + 1] - k <= TS_GAP_MIN:
                for x in range(k + 1, keys[i + 1]):
                    per_min.setdefault(x, []).append(m[k])
    out = {}
    for tks in per_min.values():
        for tk in tks:
            parts = tk.split() or [""]  # 1 つのセッションで複数のチケットを並行していたら、その分をさらに等分する
            for p in parts:
                out[p] = out.get(p, 0) + 1 / len(tks) / len(parts)
    for k in [k for k in out if k in REDMINE_MISSING]:  # Redmine に無い番号の時間は「その他」へ
        out[""] = out.get("", 0) + out.pop(k)
    return {"tickets": {k: round(v) for k, v in out.items() if k and round(v)}, "other": round(out.get("", 0)), "total": len(per_min)}


def hrmos_cfg():
    c = load_config().get("hrmos") or {}
    if not (c.get("company") and c.get("login_id") and c.get("password")):
        raise OSError("config.json に hrmos（company・login_id・password）がありません")
    return c


def _hrmos_open(path, data=None):
    """1回だけ呼ぶ。(最後に着いた URL のパス, 本文)。"""
    global hrmos_opener
    import http.cookiejar
    import urllib.request
    from urllib.parse import urlencode
    if hrmos_opener is None:
        hrmos_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        hrmos_opener.addheaders = [("User-Agent", "Mozilla/5.0 (dev-dashboard)")]
    with hrmos_opener.open(HRMOS_BASE + path, None if data is None else urlencode(data).encode(), timeout=20) as r:
        return urlsplit(r.geturl()).path, r.read().decode("utf-8", "replace")


def hrmos_get(path):
    """ページを読む。ログインが切れていたら入り直して、もう1回だけ読む。"""
    import html
    import urllib.error
    cfg = hrmos_cfg()
    # ログインしていないと、ログイン画面へ送られるのではなく 404 が返る
    try:
        url, page = _hrmos_open(path)
        if "/login" not in url:
            return page
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403, 404):
            raise
    login = f"/{cfg['company']}/login"
    _, form = _hrmos_open(login)
    m = HRMOS_TOKEN.search(form)
    url, _ = _hrmos_open(login, [("utf8", "✓"), ("authenticity_token", html.unescape(m.group(1)) if m else ""),
                                 ("user[login_id]", cfg["login_id"]), ("user[password]", cfg["password"]), ("Submit", "ログイン")])
    if "/login" in url:
        raise OSError("HRMOS にログインできませんでした（ID・パスワードを確かめてください）")
    url, page = _hrmos_open(path)
    if "/login" in url:
        raise OSError("HRMOS にログインしましたが、ページを開けませんでした")
    return page


def hrmos_day_id(date):
    """その日の日報の ID（月の一覧のリンクから拾う）。date は datetime.date。

    ID は変わらないので、一度読んだ月の分は覚えておく（HRMOS への読み込みを減らす。再起動で忘れる）。
    """
    key = (date.year, date.month)
    if key not in hrmos_ids:
        page = hrmos_get(f"/daily_reports?month={date:%Y-%m}")
        found = {int(m.group(2)): m.group(1) for m in re.finditer(r'href="/daily_reports/(\d+)"[^>]*>\s*(\d{1,2})\s', page)}
        if found:
            hrmos_ids[key] = found
    if date.day in hrmos_ids.get(key, {}):
        return hrmos_ids[key][date.day]
    raise OSError(f"{date:%Y-%m-%d} の日報が月の一覧に見つかりません")


from html.parser import HTMLParser  # noqa: E402


class _HrmosForm(HTMLParser):
    """編集画面のフォームの項目を、ブラウザが送るのと同じ並びで集める: [name, value, 選択肢の表示名]。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields, self.token, self.date = [], "", ""
        self._sel = self._opt = self._ta = None

    def _close_opt(self):
        o, self._opt = self._opt, None
        if o is None or self._sel is None:
            return
        if o["selected"] or not self._sel["seen"]:  # 選択が無ければ先頭の選択肢（ブラウザと同じ）
            self._sel.update(value=o["value"], label=o["text"].strip())
        self._sel["seen"] = True

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input":
            name = a.get("name") or ""
            if name == "authenticity_token":
                self.token = a.get("value") or ""
            if name and "disabled" not in a and a.get("type") in ("hidden", "text", "time", None):
                self.fields.append([name, a.get("value") or "", ""])
        elif tag == "select":
            self._sel = {"name": a.get("name") or "", "value": "", "label": "", "seen": False, "disabled": "disabled" in a}
        elif tag == "option":
            self._close_opt()
            if self._sel is not None:
                self._opt = {"value": a.get("value") or "", "selected": "selected" in a, "text": ""}
        elif tag == "textarea":
            self._ta = {"name": a.get("name") or "", "text": "", "disabled": "disabled" in a}

    def handle_data(self, data):
        if self._opt is not None:
            self._opt["text"] += data
        elif self._ta is not None:
            self._ta["text"] += data

    def handle_endtag(self, tag):
        if tag == "option":
            self._close_opt()
        elif tag == "select" and self._sel is not None:
            self._close_opt()
            s, self._sel = self._sel, None
            if s["name"] and not s["disabled"]:
                self.fields.append([s["name"], s["value"], s["label"]])
            elif not s["name"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["label"]):
                self.date = s["label"]  # 画面上部の日付の選択（名前の無い select）
        elif tag == "textarea" and self._ta is not None:
            t, self._ta = self._ta, None
            if t["name"] and not t["disabled"]:
                self.fields.append([t["name"], t["text"].removeprefix("\n"), ""])


def hrmos_day(day_id):
    """1日分の編集画面を読む: 送信用の token と、いまある行。"""
    p = _HrmosForm()
    p.feed(hrmos_get(f"/daily_reports/{day_id}/edit"))
    if not p.token:
        raise OSError("日報の編集画面を読めませんでした（締め済み・承認済みの日かもしれません）")
    rows = {}
    for name, value, label in p.fields:
        m = HRMOS_ROW.fullmatch(name)
        if not m or m.group(2) == "_destroy":
            continue
        r = rows.setdefault(int(m.group(1)), {})
        r[m.group(2)] = value
        if label and value:
            r[m.group(2) + "_label"] = label
    out = []
    for _, r in sorted(rows.items()):
        if not r.get("id"):
            continue  # 空の日に出る入力用の空行
        out.append({"id": r["id"], "service_name": r.get("service_name", ""), "plan": r.get("plan_time_str", ""),
                    "result": r.get("result_time_str", ""), "notes": r.get("notes", "").replace("\r\n", "\n").replace("\r", "\n"),
                    "partner": r.get("business_partner_id_label", ""), "project": r.get("project_id_label", ""),
                    "category": " / ".join(x for x in (r.get("service_large_category_id_label", ""), r.get("service_medium_category_id_label", ""),
                                                      r.get("service_category_id_label", "")) if x),
                    **{k: r.get(k, "") for k in HRMOS_ID_FIELDS}})
    return {"token": p.token, "rows": out, "page_date": p.date}


def hrmos_reorder(day_id, ids):
    """日報の行の並び順を変える。ids = 全行の id を並べたい順に。
    HRMOS の日報の詳細画面の ▲▼ と同じ呼び出し（PUT /reports/reorder_sequence?daily_report_id=… に {行id: 0始まりの順番} を全行分）。
    編集画面のフォームには順番の項目が無く、並び順はこの呼び出しでしか変えられない。"""
    import html
    import urllib.request
    from urllib.parse import urlencode
    page = hrmos_get(f"/daily_reports/{day_id}")  # ログインの確認と、送信用の token（ブラウザは meta の csrf-token を送る）
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
    if not m:
        raise OSError("日報の詳細画面から送信用の token を読めませんでした")
    shown = re.findall(r'<tr id="(\d+)"', page)
    if sorted(shown) != sorted(ids):
        raise OSError("並べる行が HRMOS の行と合いません（画面を取り直してください）")
    req = urllib.request.Request(f"{HRMOS_BASE}/reports/reorder_sequence?daily_report_id={day_id}",
                                 data=urlencode([(i, n) for n, i in enumerate(ids)]).encode(), method="PUT",
                                 headers={"X-CSRF-Token": html.unescape(m.group(1)), "X-Requested-With": "XMLHttpRequest",
                                          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Accept": "*/*"})
    with hrmos_opener.open(req, timeout=20) as r:
        r.read()
    now = [r["id"] for r in hrmos_day(day_id)["rows"]]  # 読み直して、本当にその順になったか確かめる
    if now != list(ids):
        raise OSError("並び替えを送りましたが、HRMOS の並びが変わっていません（HRMOS の画面で確かめてください）")


def hrmos_time(value, default="00:00"):
    """ "1:5"・"0:0"・"0"（時だけ）・"01:05"・全角を "01:05" の形にそろえる。空なら default。不正なら ValueError。"""
    v = str(value or "").strip().translate(str.maketrans("０１２３４５６７８９：", "0123456789:"))
    if not v:
        return default
    if re.fullmatch(r"\d{1,2}", v):
        v += ":00"
    m = re.fullmatch(r"(\d{1,2}):(\d{1,2})", v)
    if m:
        v = f"{m.group(1)}:{int(m.group(2)):02d}"
    m = HRMOS_TIME.fullmatch(v)
    if not m or int(m.group(2)) > 59 or int(m.group(1)) > 23:
        raise ValueError(f"時間「{v}」が不正です（0:00〜23:59）")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def nippo_date(text):
    """ "today" / "YYYY-MM-DD" を datetime.date に。today は朝 4:00 区切りの今日。"""
    from datetime import date, datetime
    if not text or text == "today":
        return date.fromtimestamp(day_start())
    return datetime.strptime(text, "%Y-%m-%d").date()


def nippo_view(date_text):
    """日報の1日分。今日なら、チケット別の作業時間の下書き（timesheet）も付ける。"""
    try:
        d = nippo_date(date_text)
        today_d = nippo_date("today")
        work_total = ""
        with hrmos_lock:
            day_id = hrmos_day_id(d)
            day = hrmos_day(day_id)
            if d == today_d:
                # 総労働時間（退勤の打刻後に出る）は表示画面にだけある。今日の日報を開いたときだけ読む
                m = re.search(r"総労働時間(?:&nbsp;|\s)*(\d{1,2}:\d{2})", hrmos_get(f"/daily_reports/{day_id}"))
                work_total = m.group(1) if m else ""
    except Exception as e:
        return {"error": f"HRMOS から日報を取れませんでした: {e}"}, 502
    out = {"date": d.isoformat(), "today": today_d.isoformat(), "is_today": d == today_d, "id": day_id,
           "url": f"{HRMOS_BASE}/daily_reports/{day_id}", "rows": day["rows"]}
    if d == today_d:
        out["work_total"] = work_total
        out["timesheet"] = timesheet_today()
    return out, 200


NIPPO_PREV_DAYS = 62  # 「前回の日報をコピー」でさかのぼる日数（HRMOS の画面のコピーは5日前まで）


def nippo_prev(date_text):
    """date より前で、行のある一番近い日の日報（「前回の日報をコピー」の元）。休みの日など行の無い日は飛ばす。"""
    from datetime import timedelta
    try:
        d = nippo_date(date_text)
        with hrmos_lock:
            for k in range(1, NIPPO_PREV_DAYS + 1):
                p = d - timedelta(days=k)
                try:
                    day_id = hrmos_day_id(p)
                except OSError:
                    continue  # 月の一覧に無い日
                rows = hrmos_day(day_id)["rows"]
                if rows:
                    return {"date": p.isoformat(), "id": day_id, "url": f"{HRMOS_BASE}/daily_reports/{day_id}", "rows": rows}, 200
    except Exception as e:
        return {"error": f"HRMOS から前回の日報を取れませんでした: {e}"}, 502
    return {"error": f"{d:%Y-%m-%d} より前の {NIPPO_PREV_DAYS} 日間に、行のある日報がありません"}, 404


def nippo_save(req):
    """日報を登録する。updates = いまある行の変更（id・plan・result・notes）、adds = 足す行、deletes = 削除する行の id。dry なら送る内容だけ返す。"""
    try:
        d = nippo_date(req.get("date"))
        updates, adds = req.get("updates") or [], req.get("adds") or []
        if not isinstance(updates, list) or not isinstance(adds, list):
            raise ValueError("updates / adds が不正です")
        defaults = (load_config().get("hrmos") or {}).get("row_defaults") or {}
        with hrmos_lock:
            day_id = hrmos_day_id(d)
            cur = hrmos_day(day_id)   # 送る直前に読み直す（token と、いまの値）
            known = {r["id"]: r for r in cur["rows"]}
            key = "daily_report[reports_attributes][%d][%s]"
            data, n, summary = [("utf8", "✓"), ("_method", "patch"), ("authenticity_token", cur["token"])], 0, []
            # HRMOS は未来の日付に実績を入れられない。未来の日は、実績をいまの値（足す行は 0:00）のまま送る
            if d > nippo_date("today"):
                updates = [{k: v for k, v in u.items() if k != "result"} for u in updates]
                adds = [{**a, "result": ""} for a in adds]
            wanted = {}
            for u in updates:
                if str(u.get("id")) not in known:
                    raise ValueError(f"行 {u.get('id')} が HRMOS にありません（画面を取り直してください）")
                wanted[str(u.get("id"))] = u
            # 🚨 いまある行は「全部」送る（変えていない行も、いまの予定・実績・備考をそのまま付ける）。
            #    HRMOS は送られてこなかった行の時間を 0:00 に書き換える（2026-11-14 に、変えた行だけ送って他の行の時間を消した）。
            #    ブラウザの画面も全行を送っている。
            deletes = {str(x) for x in (req.get("deletes") or [])}
            if deletes - set(known):
                raise ValueError("削除する行が HRMOS にありません（画面を取り直してください）")
            changed = 0
            for r in cur["rows"]:
                if r["id"] in deletes:  # 行の削除は、画面の「削除」と同じ _destroy=1 を送る
                    data += [(key % (n, "id"), r["id"]), (key % (n, "_destroy"), "1")]
                    summary.append(f"削除 {r['service_name'][:40]}（予定 {hrmos_time(r['plan'])}・実績 {hrmos_time(r['result'])}）")
                    changed += 1
                    n += 1
                    continue
                u = wanted.get(r["id"], {})
                new = {"plan_time_str": hrmos_time(u.get("plan"), hrmos_time(r["plan"])), "result_time_str": hrmos_time(u.get("result"), hrmos_time(r["result"])),
                       "notes": str(u.get("notes", r["notes"])).replace("\r\n", "\n")[:2000]}
                if (new["plan_time_str"], new["result_time_str"], new["notes"]) != (hrmos_time(r["plan"]), hrmos_time(r["result"]), r["notes"]):
                    summary.append(f"変更 {r['service_name'][:40]}: 予定 {new['plan_time_str']}・実績 {new['result_time_str']}")
                    changed += 1
                new["notes"] = new["notes"].replace("\n", "\r\n")  # 備考の改行はブラウザが送る形（CRLF）にする
                data += [(key % (n, "id"), r["id"])] + [(key % (n, k), v) for k, v in new.items()]
                n += 1
            names = {r["service_name"].strip() for r in cur["rows"] if r["id"] not in deletes}
            for a in adds:
                name = str(a.get("service_name") or "").strip()[:255]
                if not name:
                    raise ValueError("足す行の業務名が空です")
                if name in names:
                    continue  # 同じ業務名の行がもうある（二重に足さない）
                names.add(name)
                ids = {k: str(a.get(k) or defaults.get(k) or "") for k in HRMOS_ID_FIELDS}
                if not ids["business_partner_id"] or not ids["project_id"]:
                    raise ValueError("足す行の取引先・プロジェクトが決まりません（config.json の hrmos.row_defaults）")
                data += [(key % (n, k), v) for k, v in ids.items()]
                data += [(key % (n, "service_name"), name), (key % (n, "plan_time_str"), hrmos_time(a.get("plan"))),
                         (key % (n, "result_time_str"), hrmos_time(a.get("result"))), (key % (n, "notes"), str(a.get("notes") or "").replace("\r\n", "\n")[:2000].replace("\n", "\r\n"))]
                summary.append(f"追加 {name[:40]}: 予定 {hrmos_time(a.get('plan'))}・実績 {hrmos_time(a.get('result'))}")
                n += 1
                changed += 1
            # 並び順（order = 残す行の id を並べたい順に）。いまの並び（削除する行を除く）と違うときだけ並べ替える。
            # 足す行は HRMOS が末尾に足すので、登録の後に読み直して最後に回す
            order = [str(x) for x in (req.get("order") or [])]
            keep = [r["id"] for r in cur["rows"] if r["id"] not in deletes]
            if order and sorted(order) != sorted(keep):
                raise ValueError("並び順の行が HRMOS の行と合いません（画面を取り直してください）")
            reorder = bool(order) and order != keep
            if reorder:
                summary.append("並び替え: " + " → ".join(known[i]["service_name"][:20] for i in order))
            if not changed and not reorder:
                return {"ok": True, "changed": 0, "summary": [], "message": "変更はありません"}, 200
            if req.get("dry"):
                return {"dry": True, "changed": changed + reorder, "sent_rows": n, "summary": summary, "fields": [[k, v] for k, v in data if k != "authenticity_token"]}, 200
            left = []
            if changed:
                _, page = _hrmos_open(f"/daily_reports/{day_id}", data)
                # 削除を頼んだ行が本当に消えたかを読み直して確かめる
                left = [r["service_name"][:40] for r in hrmos_day(day_id)["rows"] if r["id"] in deletes] if deletes and "登録が完了しました" in page else []
            else:
                page = "登録が完了しました"  # 並び替えだけ（行の内容は送らない）
            if reorder and "登録が完了しました" in page and not left:
                try:
                    now = [r["id"] for r in hrmos_day(day_id)["rows"]]
                    want = [i for i in order if i in now] + [i for i in now if i not in order]
                    if want != now:
                        hrmos_reorder(day_id, want)
                except Exception as e:
                    return {"error": ("行の登録はしましたが、" if changed else "") + f"並び替えに失敗しました: {e}"}, 502
    except ValueError as e:
        return {"error": str(e)}, 400
    except Exception as e:
        return {"error": f"HRMOS に登録できませんでした: {e}"}, 502
    if "登録が完了しました" in page and left:
        return {"error": "登録はされましたが、次の行が削除されずに残っています: " + " / ".join(left)}, 409
    if "登録が完了しました" in page:
        return {"ok": True, "changed": changed + reorder, "summary": summary, "url": f"{HRMOS_BASE}/daily_reports/{day_id}"}, 200
    errs = re.findall(r"\d+行目：[^<\n]+", page) or (["エラーが発生しました。管理者にお問合せください。"] if "エラーが発生しました" in page else [])
    return {"error": "HRMOS が登録を受け付けませんでした: " + (" / ".join(errs) if errs else "理由は画面から読み取れませんでした（HRMOS の画面で確かめてください）")}, 409


# ---- hub の監視（/na-order で固定したチケット。2026-11-25〜） ----
# 固定したチケットごとに、担当の枠・スキル単位の段階・状態（処理中・確認待ち…）を 20 秒ごとに判定し、
# ~/.local/share/ticket-v2/hub/watch.json に書く（hub の /na-watch が読む）。確認待ち・レビューに変わったら
# tmux（ステータス行の件数・数秒のメッセージ）と Slack DM で知らせる。固定の順は hub が order.json に持つ（hub_redmine.py の /na-order）
HUB_STATE_DIR = os.path.join(HOME, ".local", "share", "ticket-v2", "hub")
HUB_ORDER = os.path.join(HUB_STATE_DIR, "order.json")
HUB_WATCH = os.path.join(HUB_STATE_DIR, "watch.json")
HUB_NOTIFY = os.path.join(HUB_STATE_DIR, "watch_notify.json")  # 前回の状態（変わったときだけ知らせる）
SLACK_DM = os.path.join(HOME, ".claude", "hooks", "slack-dm.sh")
WATCH_FLOW = ["ct-redmine", "ct-analyze", "ct-architect", "ct-sweep", "ct-scope", "ct-planner", "ct-issue-docs", "ct-ship-loop", "ct-finish"]
WATCH_OPTIONAL = {"ct-sweep", "ct-scope"}
WATCH_SHORT = {s: s.removeprefix("ct-") for s in WATCH_FLOW}
WATCH_DAYS = 14
WATCH_INTERVAL = 20
WATCH_ATTENTION = {"wait", "question", "next"}  # 確認待ち（ユーザーが見る番）
WATCH_STATE_LABEL = {"busy": "処理中", "wait": "確認待ち（許可）", "question": "確認待ち（質問）", "next": "確認待ち（次の指示）",
                     "idle": "入力待ち", "stopped": "停止中", "none": "枠なし"}
WATCH_STATUS_FMT = "#{?@hub_attention,#[fg=black#,bg=yellow] 確認待ち #{@hub_attention} #[default] ,}"
watch_lock = threading.Lock()
watch_files = {}   # 記録ファイル -> {"offset", "cwd", "ticket", "open"}（追記分だけ読む）
watch_skills = {}  # チケット番号 -> [{"skill", "start", "end", "result"}]（result: running / done / question）
watch_cache = {"at": 0, "items": [], "attention": 0}


def watch_order():
    try:
        with open(HUB_ORDER, encoding="utf-8") as f:
            return [str(n) for n in json.load(f).get("order") or []]
    except (OSError, ValueError):
        return []


def _watch_event(ticket, skill, ts):
    evs = watch_skills.setdefault(ticket, [])
    ev = {"skill": skill, "start": ts, "end": 0, "result": "running"}
    evs.append(ev)
    del evs[:-60]
    return ev


def _watch_lines(st, lines, skills):
    """Claude の記録の追記分から、チケット番号付きのスキル実行と、その終わり（end_turn。質問で終わったか）を拾う。"""
    for line in lines:
        is_user = '"type":"user"' in line
        has_skill_tool = '"name":"Skill"' in line
        is_end = '"end_turn"' in line and '"assistant"' in line
        if not (is_user or has_skill_tool or is_end or ('"cwd"' in line and not st.get("cwd"))):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        st["cwd"] = d.get("cwd") or st.get("cwd", "")
        if env_of(st.get("cwd")) not in ENV_DIRS.values():
            continue  # 環境1〜4の作業フォルダのセッションだけ（hub・一時フォルダは数えない）
        ts = iso_ts(d.get("timestamp"))
        if not ts or d.get("isMeta") or d.get("isCompactSummary") or d.get("isSidechain"):
            continue  # 圧縮後に差し込まれる「前に使ったスキル」の一覧・サブエージェントの会話は数えない
        if is_user:
            tks = claude_work_tickets(d)
            if tks:
                st["ticket"] = tks[0]
            if "<command-name>" in line:
                for name in SKILL_CMD.findall(json.dumps(d.get("message", {}), ensure_ascii=False)):
                    if name.startswith("ct-") and name in skills:
                        tk = tks[0] if tks else st.get("ticket", "")
                        if tk:
                            st["open"] = _watch_event(tk, name, ts)
        if has_skill_tool:
            for b in (d.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
                    inp = b.get("input") or {}
                    name = inp.get("skill", "")
                    if not name.startswith("ct-"):
                        continue
                    tk = main_ticket(str(inp.get("args") or "")) or st.get("ticket", "")
                    if tk:
                        st["open"] = _watch_event(tk, name, ts)
        if is_end and st.get("open") and st["open"]["result"] != "done":
            msg = d.get("message") or {}
            if msg.get("stop_reason") == "end_turn":
                text = "\n".join(b.get("text", "") for b in msg.get("content") or [] if isinstance(b, dict) and b.get("type") == "text")
                st["open"]["end"] = ts
                st["open"]["result"] = "question" if is_question(text) else "done"


def scan_watch_skills():
    skills = known_skills()
    limit = time.time() - WATCH_DAYS * 86400
    files = sorted(glob.glob(os.path.join(HOME, ".claude", "projects", "*", "*.jsonl")), key=os.path.getmtime)
    for path in files:
        try:
            if os.path.getmtime(path) < limit:
                continue
            st = watch_files.setdefault(path, {"offset": 0, "cwd": ""})
            lines = read_new_lines(path, st)
        except OSError:
            continue
        if lines:
            with watch_lock:
                _watch_lines(st, lines, skills)


def watch_flow(n):
    """スキル単位の段階: 流れの各スキルの印（done 済み / running 実行中 / question 質問中 / "" 未実行）と、最後のスキル。"""
    with watch_lock:
        evs = sorted(watch_skills.get(n, []), key=lambda e: e["start"])  # ファイルの読む順は時刻順ではない
    marks = {ev["skill"]: ev["result"] for ev in evs if ev["skill"] in WATCH_SHORT}  # 同じスキルは最後の実行の結果
    last = next((ev for ev in reversed(evs) if ev["skill"] in WATCH_SHORT), None)
    # 後の段階が始まっていれば、前の段階は済んだものとみなす（ct-ship-loop の中で ct-finish が動く等）
    reached = max((WATCH_FLOW.index(s) for s in marks), default=-1)
    flow = []
    for i, s in enumerate(WATCH_FLOW):
        m = marks.get(s, "")
        if not m and i < reached and s not in WATCH_OPTIONAL:
            m = "skip"
        if m in ("running", "question") and last and last["skill"] != s:
            m = "done"  # 途中で別のスキルに移った（終わりの区切りが無いまま）
        flow.append({"skill": s, "short": WATCH_SHORT[s], "mark": m, "optional": s in WATCH_OPTIONAL})
    pr_turn = [ev for ev in evs if ev["skill"] == "ct-pr-turn"]
    lastf = next((ev for ev in reversed(evs) if ev["skill"] in WATCH_SHORT or ev["skill"] == "ct-pr-turn"), None)
    return flow, lastf, (pr_turn[-1] if pr_turn else None), last


def watch_item(n, f, slots):
    flow, last, pr_turn, last_flow = watch_flow(n)
    mine = [s for s in slots if s["kind"] == "claude" and s["state"] != "stopped" and n in (s.get("tickets") or [s.get("ticket")])]
    rank = {"wait": 4, "busy": 3, "idle": 2}
    slot = max(mine, key=lambda s: rank.get(s["state"], 0)) if mine else None
    skill = (last or {}).get("skill") or (slot or {}).get("skill", "")
    if not slot:
        state = "none"
    elif slot["state"] in ("busy", "wait"):
        state = slot["state"]
    elif (slot.get("skill") and not slot.get("skill_done")) or (last and last["result"] == "question"):
        state = "question"  # スキルの返答が質問で終わっている（答え待ち。ct-handoff など流れの外のスキルも含む）
    elif last and last["result"] == "done":
        state = "next"      # 流れのスキルが終わり、次の指示待ち
    else:
        state = "idle"
    ball = (f.get("ball") or {})
    review = ball.get("kind") in ("review_in", "fix")
    if ball.get("kind") == "review_in":
        rv_urls = [r.get("url") for r in f.get("review_requested") or [] if r.get("url")]
    else:
        rv_urls = [p.get("url") for p in f.get("prs") or [] if p.get("state") == "open" and p.get("decision") == "CHANGES_REQUESTED" and p.get("url")]
    ev = lambda e: {"skill": e["skill"], "result": e["result"], "start": e["start"], "end": e["end"]} if e else None
    stage = next((x["short"] for x in reversed(flow) if x["mark"] in ("done", "running", "question")), "")
    return {"id": n, "subject": f.get("subject", ""), "status": f.get("status", ""), "priority": f.get("priority", ""),
            "url": f.get("url", ""), "closed": f.get("ball", {}).get("kind") == "done",
            "slot": slot["slot"] if slot else None, "env": slot["env"] if slot else "", "slots": [s["slot"] for s in mine],
            "state": state, "state_label": WATCH_STATE_LABEL[state], "attention": state in WATCH_ATTENTION or review,
            "skill": skill, "stage": stage, "flow": flow, "phase": f.get("phase"),
            "pr_turn": {"result": pr_turn["result"], "start": pr_turn["start"]} if pr_turn else None,
            "review": {"kind": ball.get("kind"), "label": ball.get("label"), "why": ball.get("why"), "urls": rv_urls} if review else None,
            "last": ev(last), "last_flow": ev(last_flow),
            "ball": ball, "prs": [{"repo": p.get("repo"), "number": p.get("number"), "state": p.get("state"), "url": p.get("url"),
                                    "decision": p.get("decision")} for p in f.get("prs") or []]}


def watch_build(order=None):
    order = order if order is not None else watch_order()
    panes = ai_panes()
    slots = panes.get("slots", [])
    fv_items = focus_view()["items"]
    fv = {str(i["id"]): i for i in fv_items}
    items = []
    for n in order:
        f = fv.get(n)
        if f is None:
            one = focus_view(only=n)["items"]
            f = one[0] if one else {}
        items.append(watch_item(n, f, slots))
    return {"at": time.time(), "items": items, "attention": sum(1 for i in items if i["attention"]), "order": order,
            "_fv": fv_items, "_slots": slots}  # _ で始まるものは外に出さない（watch_once が外す）


def tmux_notify(msg):
    try:
        clients = tmux("list-clients", "-t", TMUX_SESSION, "-F", "#{client_name}").stdout.split()
        for c in clients:
            tmux("display-message", "-c", c, "-d", "6000", msg)
    except (OSError, subprocess.TimeoutExpired):
        pass


def tmux_attention(count):
    """ステータス行の右に「確認待ち N」を出す（@hub_attention）。tmuxp を読み直すと書式が戻るので、毎回確かめて足す。"""
    try:
        tmux("set-option", "-t", TMUX_SESSION, "@hub_attention", str(count) if count else "")
        cur = tmux("show-options", "-v", "-t", TMUX_SESSION, "status-right").stdout.rstrip("\n")
        if "@hub_attention" not in cur:
            if not cur:
                cur = tmux("show-options", "-gv", "status-right").stdout.rstrip("\n")
            tmux("set-option", "-t", TMUX_SESSION, "status-right", WATCH_STATUS_FMT + cur)
    except (OSError, subprocess.TimeoutExpired):
        pass


def slack_dm(msg):
    if os.access(SLACK_DM, os.X_OK):
        try:
            subprocess.run([SLACK_DM, msg, "hub 監視"], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass


def watch_notify(items):
    """前回から変わった「確認待ち」「レビュー」だけを知らせる。初回（前回の記録が無い）は記録だけして知らせない。"""
    try:
        with open(HUB_NOTIFY, encoding="utf-8") as f:
            prev = json.load(f)
        first = False
    except (OSError, ValueError):
        prev, first = {}, True
    now = {}
    msgs = []
    for i in items:
        key = f"{i['state']}:{i['skill']}" if i["state"] in WATCH_ATTENTION else ""
        rkey = (i.get("review") or {}).get("kind") or ""
        now[i["id"]] = {"state": key, "review": rkey}
        if i["id"] not in prev:
            continue  # 固定したばかりのチケットは、今の状態を覚えるだけ（固定した直後に知らせない）
        p = prev[i["id"]]
        where = f"[{i['slot']}] " if i["slot"] is not None else ""
        if key and key != p.get("state"):
            what = {"wait": "許可の確認", "question": f"{WATCH_SHORT.get(i['skill'], i['skill'])} の質問",
                    "next": f"{WATCH_SHORT.get(i['skill'], i['skill'])} 完了・次の指示"}[i["state"]]
            msgs.append(f"👀 #{i['id']} {where}{what}（{i['subject'][:30]}）")
        if rkey and rkey != p.get("review"):
            msgs.append(f"#{i['id']} {i['review']['label']}（{i['review']['why'][:60]}）")
    try:
        tmp = HUB_NOTIFY + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(now, f, ensure_ascii=False)
        os.replace(tmp, HUB_NOTIFY)
    except OSError:
        pass
    if first or not msgs:
        return []
    tmux_notify(" / ".join(msgs))
    slack_dm("hub 監視\n" + "\n".join(msgs))
    return msgs


def watch_once():
    scan_watch_skills()
    d = watch_build()
    fv_items, slots = d.pop("_fv"), d.pop("_slots")
    sent = None
    try:
        sent = autopilot(d, slots)  # B・C・F: 次のスキル・コミット・ct-pr-turn を自動で頼む（1回に1件）
    except Exception as e:
        print(f"{time.strftime('%F %T')} 自動の依頼に失敗: {e}", file=sys.stderr, flush=True)
    for i in d["items"]:
        if i["id"] == sent:  # 送った直後は処理中として扱う（「次の指示待ち」を知らせない）
            i["state"], i["state_label"], i["attention"] = "busy", "処理中（自動で依頼）", False
    d["attention"] = sum(1 for i in d["items"] if i["attention"])
    d["auto"] = {k: {"slot": v.get("slot"), "plan": v.get("plan"), "go": v.get("go"), "last": (v.get("log") or [None])[-1]}
                 for k, v in _json_load(HUB_AUTO, {"tickets": {}}).get("tickets", {}).items()}
    d["notified"] = watch_notify(d["items"]) + review_notify(fv_items, set(d["order"]))
    try:
        d["docker"] = docker_check(slots)
    except Exception as e:
        print(f"{time.strftime('%F %T')} 開発用サーバーの順番待ちの確認に失敗: {e}", file=sys.stderr, flush=True)
    watch_cache.update(d)
    tmux_attention(d["attention"])
    try:
        os.makedirs(HUB_STATE_DIR, exist_ok=True)
        tmp = HUB_WATCH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, HUB_WATCH)
    except OSError:
        pass
    return d


def watch_loop():
    while True:
        try:
            watch_once()
        except Exception as e:  # 失敗しても次の回でやり直す
            print(f"{time.strftime('%F %T')} 監視の判定に失敗: {e}", file=sys.stderr, flush=True)
        time.sleep(WATCH_INTERVAL)


# ---- hub の自動の依頼（B 次のスキル・C 資料の後のコミット・F レビュー。2026-11-25〜） ----
# /na-next で開始したチケット（autopilot.json に載ったもの）だけ、枠のスキルが終わったら次のスキルを自動で頼む。
# ct-analyze・ct-architect・ct-planner の後は止めて確認を待つ（/na-next で次へ）。ct-issue-docs の後はコミットを1回頼んで止める
# （ct-ship-loop 以降は /na-go。D）。レビュー依頼・戻りは、固定（/na-order）したら ct-pr-turn を頼み、固定していなければ知らせだけ。
# 送るのは hub の na_to.py（偶数枠・処理中・入力欄に文字がある枠・本番系の枠には送らない）。失敗は tmux と Slack DM で知らせる
HUB_AUTO = os.path.join(HUB_STATE_DIR, "autopilot.json")
HUB_SLOTS = os.path.join(HUB_STATE_DIR, "slots.json")  # /na-slot off で除外した枠
NA_TO = os.path.join(HUB_STATE_DIR, "bin", "na_to.py")
AUTO_NEXT = {"ct-redmine": "ct-analyze", "ct-sweep": "ct-planner", "ct-scope": "ct-planner", "ct-issue-docs": "commit"}
AUTO_STOP = {"ct-analyze", "ct-architect", "ct-planner"}  # 次へ進む前にユーザーが確認する段階
MANUAL_NEXT = {None: "ct-redmine", "ct-redmine": "ct-analyze", "ct-analyze": "ct-architect", "ct-architect": "ct-planner",
               "ct-sweep": "ct-planner", "ct-scope": "ct-planner", "ct-planner": "ct-issue-docs", "ct-issue-docs": "commit"}
ANALYZE_NOTE = ("初期調査は release が対象なので、基本はステージング（https://group.corich.mobi/naga3/events 。団体 naga3 は自由に使ってよい）で確かめてください。"
                "テスティングは https://group.test.corich.asia/nagayoshi/events （団体 nagayoshi は自由に使ってよい）。"
                "ローカルの DB・Redis・サーバーが必要なときだけ、開発用サーバーは同時に1台なので、使う前に "
                "`python3 ~/.local/share/ticket-v2/hub/bin/hub_docker.py wait <番号>`（Bash の run_in_background で実行し、終了コード 0 で使ってよい・3 ならもう一度）で順番を待ち、"
                "使い終わったら `hub_docker.py release <番号>` を実行してください。")
auto_lock = threading.Lock()


def _json_load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _json_save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def slots_off():
    return {int(x) for x in _json_load(HUB_SLOTS, {}).get("off") or []}


def auto_text(skill, n, item, plan=None):
    """枠に送る依頼文。skill は ct-… か commit・pr-turn。"""
    if skill == "ct-analyze":
        return f"/ct-analyze {n} {ANALYZE_NOTE}"
    if skill == "commit":
        return (f"/ct-commit {n} ct-issue-docs で作った issue docs（docs/issues/active/{n}_*/）だけをコミットしてください。"
                f"ブランチはこの環境の CLAUDE.local.md の決まり（設計だけをして別の環境で実装するなら design/{n}）に従ってください。push はしないでください。")
    if skill == "pr-turn":
        urls = " ".join((item.get("review") or {}).get("urls") or [])
        return f"/ct-pr-turn {urls} #{n}".replace("  ", " ")
    return f"/{skill} {n}"


SLOT_PREFER = {"design": [9, 11, 1, 3, 5, 7],   # 調査・設計の流れ: 設計用の環境3・4を先に（環境3・4は release で設計する）
               "review": [9, 11, 1, 3, 5, 7],   # 他の人の PR のレビュー
               "fix": [1, 3, 5, 7]}             # 自分の PR の戻り（修正）: ブランチを触るので環境1・2だけ


def free_slot(items, slots, auto, purpose="design"):
    """空いている Claude の枠（入力待ち・作業中のチケットが無い・除外していない・他のチケットに割り当てていない）。SLOT_PREFER の順。"""
    off = slots_off()
    bound = {t.get("slot") for k, t in auto.get("tickets", {}).items() if t.get("slot") is not None}
    bound |= {i["slot"] for i in items if i.get("slot") is not None}
    prefer = SLOT_PREFER.get(purpose, SLOT_PREFER["design"])
    for s in sorted((s for s in slots if s["slot"] in prefer), key=lambda s: prefer.index(s["slot"])):
        if s["kind"] == "claude" and s["slot"] % 2 == 1 and s["state"] == "idle" and not (s.get("tickets") or s.get("ticket")) \
                and s["slot"] not in off and s["slot"] not in bound:
            return s["slot"]
    return None


def na_to_send(slot, text):
    """hub の na_to.py で枠に送る。(成功したか, 結果の文)

    na_to.py（tmux_link）は TMUX_PANE のセッションの中で枠を探す。launchd から呼ぶと tmux の外なので、
    ticket_v2_project の枠を1つ TMUX_PANE に入れて、ほかのセッションの monitor タブを拾わないようにする。
    """
    target = (slot_pane(slot) or {}).get("id")
    if not target:
        return False, f"[{slot}] の枠が見つかりません"
    # 送り先そのものを入れると tmux_link が「自分（self）」と見なして送らないので、同じセッションの別の枠を入れる
    ids = tmux("list-panes", "-s", "-t", TMUX_SESSION, "-F", "#{pane_id}").stdout.split()
    pane = next((x for x in ids if x != target), None)
    if not pane:
        return False, f"{TMUX_SESSION} に送り先以外の枠がありません"
    try:
        r = subprocess.run([sys.executable, NA_TO, str(slot), text], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "TMUX_PANE": pane})
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"送信の処理が失敗: {e}"
    out = (r.stdout or r.stderr or "").strip()
    return r.returncode == 0 and out.startswith("✅"), out


def _auto_record(auto, n, slot, skill, text, ok, msg, key=None):
    t = auto.setdefault("tickets", {}).setdefault(n, {"plan": {}, "handled": [], "log": []})
    if ok:
        t["slot"] = slot
    if key and ok:
        t["handled"] = (t.get("handled") or [])[-30:] + [key]
    t.setdefault("log", []).append({"at": time.time(), "slot": slot, "skill": skill, "ok": ok, "msg": msg[:200], "text": text[:300]})
    del t["log"][:-20]


def next_skill(item, plan, manual):
    """最後の流れのスキルから、次に頼むもの（ct-… / commit）。止める段階・終わっていないときは None（manual は止める段階でも進める）。"""
    last = item.get("last_flow")
    if last and last.get("result") != "done":
        return None
    sk = last["skill"] if last else None
    if not manual and (sk is None or sk in AUTO_STOP):
        return None
    if sk == "ct-architect":
        nxt = "ct-sweep" if plan.get("sweep") else ("ct-scope" if plan.get("scope") else "ct-planner")
    elif sk == "ct-sweep":
        nxt = "ct-scope" if plan.get("scope") else "ct-planner"
    else:
        nxt = (MANUAL_NEXT if manual else AUTO_NEXT).get(sk)
    # 次のスキルがすでに動いた記録があれば頼まない（終わったチケットで ct-redmine をコメントに使ったとき等）
    marks = {x["skill"]: x["mark"] for x in item.get("flow") or []}
    if nxt and nxt.startswith("ct-") and marks.get(nxt) in ("done", "running", "question"):
        return None
    return nxt


def autopilot(d, slots):
    """watch_once から呼ぶ。1回に送るのは1件だけ（送った枠の状態を次の判定で見てから続ける）。送ったチケットの番号を返す。"""
    with auto_lock:
        auto = _json_load(HUB_AUTO, {"tickets": {}})
        items = d["items"]
        changed = False
        sent = None
        for i in items:
            n = i["id"]
            t = auto.get("tickets", {}).get(n)
            # レビュー（F）: 固定したチケットにレビュー依頼・戻りが来たら ct-pr-turn を頼む（枠が無ければ空いている枠）
            rv = i.get("review")
            if rv and rv.get("urls"):
                key = "review:" + ",".join(rv["urls"]) + ":" + rv["kind"]
                if key not in ((t or {}).get("handled") or []) and i["state"] in ("next", "idle", "none") and \
                        not (i.get("pr_turn") and i["pr_turn"]["result"] != "done"):
                    slot = i["slot"] if i["slot"] is not None else free_slot(items, slots, auto, "fix" if rv["kind"] == "fix" else "review")
                    if slot is None:
                        auto_fail(n, "ct-pr-turn を頼む空いている枠がありません（/na-next 番号 枠 で指定）", key + ":noslot")
                        continue
                    text = auto_text("pr-turn", n, i)
                    ok, msg = na_to_send(slot, text)
                    _auto_record(auto, n, slot, "pr-turn", text, ok, msg, key)
                    changed = True
                    if not ok:
                        auto_fail(n, f"[{slot}] に ct-pr-turn を送れません: {msg}", key)
                        continue
                    sent = n
                    break
            if t and t.get("go"):
                r = go_step(auto, i, t)
                if r is not None:
                    changed = True
                if r:
                    sent = n
                    break
                continue  # 実装を開始したチケットは、流れの自動（redmine→analyze 等）の対象にしない
            if not t or i["state"] != "next" or i["slot"] is None:
                continue
            last = i.get("last_flow") or {}
            key = f"{last.get('skill')}@{int(last.get('end') or 0)}"
            if key in (t.get("handled") or []):
                continue
            nxt = next_skill(i, t.get("plan") or {}, manual=False)
            if not nxt:
                t.setdefault("handled", []).append(key)  # 止める段階（確認待ちの知らせは watch_notify が出す）
                changed = True
                continue
            if t.get("slot") is not None and t["slot"] != i["slot"]:
                continue  # 割り当てた枠と違う枠で作業している（手で動かした）ときは触らない
            text = auto_text(nxt, n, i)
            ok, msg = na_to_send(i["slot"], text)
            _auto_record(auto, n, i["slot"], nxt, text, ok, msg, key)
            changed = True
            if not ok:
                auto_fail(n, f"[{i['slot']}] に {nxt} を送れません: {msg}", key)
                continue
            sent = n
            break
        if changed:
            _json_save(HUB_AUTO, auto)
    return sent


def auto_fail(n, msg, key=None):
    """自動の依頼の失敗を知らせる。同じ失敗（key）は1回だけ。"""
    if key:
        seen = _json_load(HUB_AUTO + ".fail", {})
        if seen.get(n) == key:
            return
        seen[n] = key
        try:
            _json_save(HUB_AUTO + ".fail", seen)
        except OSError:
            pass
    tmux_notify(f"⚠️ #{n} 自動の依頼に失敗: {msg[:80]}")
    slack_dm(f"hub 監視\n⚠️ #{n} 自動の依頼に失敗: {msg}")


def auto_start(n, slot=None, sweep=False, scope=False, dry=False):
    """/na-next 番号 [枠] [sweep] [scope]: 止まっている所から次のスキルを頼み、以後の自動の依頼の対象にする。"""
    n = str(n)
    scan_watch_skills()
    slots = ai_panes().get("slots", [])
    d = watch_build([n])
    if not d["items"]:
        return False, f"#{n} を判定できませんでした"
    i = d["items"][0]
    with auto_lock:
        auto = _json_load(HUB_AUTO, {"tickets": {}})
        t = auto.setdefault("tickets", {}).setdefault(n, {"plan": {}, "handled": [], "log": []})
        if sweep or scope:
            t["plan"] = {"sweep": sweep, "scope": scope}
        if i["state"] in ("busy", "wait", "question"):
            return False, f"#{n} は [{i['slot']}] で {i['state_label']} です。その枠で答えるか、終わってから /na-next を使ってください"
        if i["slot"] is not None and slot is not None and slot != i["slot"]:
            return False, f"#{n} は [{i['slot']}] で作業中です（1チケット1枠）。枠を変えるときはその枠を /clear してから指定してください"
        rv = i.get("review") if i.get("review") and i["review"].get("urls") and not (i.get("pr_turn") and i["pr_turn"]["result"] != "done") else None
        use = i["slot"] if i["slot"] is not None else (slot if slot is not None else free_slot(
            [x for x in watch_cache.get("items", []) if x["id"] != n], slots, {"tickets": {k: v for k, v in auto["tickets"].items() if k != n}},
            ("fix" if rv["kind"] == "fix" else "review") if rv else "design"))
        if use is None:
            return False, "空いている Claude の枠がありません（入力待ち・作業中のチケット無し・除外していない奇数枠）。枠を指定してください"
        if rv:
            nxt = "pr-turn"
        else:
            nxt = next_skill(i, t.get("plan") or {}, manual=True)
        last = i.get("last_flow") or {}
        if not nxt:
            if last.get("result") not in (None, "done"):
                return False, f"#{n} の {last.get('skill')} が終わっていません（{last.get('result')}）。その枠で続けてください"
            done = [x["skill"] for x in i["flow"] if x["mark"] == "done"]
            if "ct-issue-docs" in done:
                return False, f"#{n} は ct-issue-docs まで済んでいます。実装の開始は /na-go {n}"
            return False, f"#{n} の次のスキルを決められません（最後: {last.get('skill') or 'なし'}）"
        if nxt not in ("pr-turn", "commit") and (i.get("prs") or i.get("phase")):  # 03_progress.md は ct-issue-docs が作るのでコミットは止めない
            return False, (f"#{n} はブランチ・PR・03_progress.md があり実装まで進んでいますが、流れのスキルの記録（直近14日）は "
                           f"{last.get('skill') or 'なし'} までです。{nxt} を頼むのは止めました。その枠で直接頼んでください")
        if nxt == "commit" and any(x.get("skill") == "commit" and x.get("ok") for x in t.get("log") or []):
            return False, f"#{n} は issue docs のコミットを頼み済みです。実装の開始は /na-go {n}"
        text = auto_text(nxt, n, i)
        if dry:
            return True, f"🧪 dry-run: [{use}] ← {text[:80]}"
        ok, msg = na_to_send(use, text)
        key = f"{last.get('skill')}@{int(last.get('end') or 0)}" if nxt != "pr-turn" else \
            "review:" + ",".join(i["review"]["urls"]) + ":" + i["review"]["kind"]
        _auto_record(auto, n, use, nxt, text, ok, msg, key)
        if ok:
            t["slot"] = use
        _json_save(HUB_AUTO, auto)
    if ok:
        stop = "（この後は ct-analyze・ct-architect・ct-planner の後で止まります）" if nxt.startswith("ct-") else ""
        return True, f"{msg}{stop}"
    return False, msg


# D: 実装の開始（/na-go）。依頼文は 2026-11-25 ユーザー指定（設計ページ r1 q4 の補足）のまま。2つ目は1つ目（ct-ship-loop）が終わってから送る
GO_TEXT1 = ("/ct-ship-loop {n} コーディングはcodexで、それ以外はclaudeで行い。codexで作ったものはclaudeで、claudeで作ったものはcodexで精査して。"
            "codex使うときは適切なモデルを選ぶように調整して。ブランチ：{branch}")
GO_TEXT2 = ("/ct-finish {n} sweepは設計時に作ってたらそれを使う、作ってないなら使わない、codexにも相談して進めて。席外すので質問は全て推奨で進めて。"
            "ブラウザの動作確認もして欲しい。db,redis,ログを監視しつつ、スクショ・録画してアーティファクトにまとめて")
GO_ACTIVE = ("ship-loop", "finish")


def auto_go(n, slot=None, branch="", force=False, dry=False):
    """/na-go 番号 [枠] [--branch 名前] [force]: ct-ship-loop を頼み、終わったら ct-finish を自動で頼む。

    実装は同時に複数始めてよい。テスト・ブラウザでの確認は各枠の Claude が hub_docker.py wait で順番待ちをする（E）。
    """
    n = str(n)
    branch = branch or f"feature/{n}"
    if not re.fullmatch(r"[\w./-]{1,80}", branch):
        return False, f"ブランチ名が不正です: {branch}"
    scan_watch_skills()
    slots = ai_panes().get("slots", [])
    d = watch_build([n])
    if not d["items"]:
        return False, f"#{n} を判定できませんでした"
    i = d["items"][0]
    with auto_lock:
        auto = _json_load(HUB_AUTO, {"tickets": {}})
        # 2026-11-25 E（開発用サーバーの順番待ち hub_docker.py）ができたので、実装は同時に複数始めてよい。
        # テスト・ブラウザでの確認だけ、各環境の Claude が hub_docker.py wait で順番待ちをする
        g = (auto.get("tickets", {}).get(n) or {}).get("go") or {}
        if g.get("stage") in GO_ACTIVE:
            return False, f"#{n} は実装を開始済みです（{g['stage']}・[{g.get('slot')}]）"
        if i["state"] in ("busy", "wait", "question"):
            return False, f"#{n} は [{i['slot']}] で {i['state_label']} です。終わってから /na-go を使ってください"
        marks = {x["skill"]: x["mark"] for x in i["flow"]}
        if marks.get("ct-issue-docs") != "done" and not force:
            return False, f"#{n} は ct-issue-docs の記録（直近14日）がありません。設計を記録の外で済ませたなら /na-go {n} force"
        if marks.get("ct-ship-loop") or marks.get("ct-finish") in ("done", "running", "question"):
            if not force:
                return False, (f"#{n} は ct-ship-loop・ct-finish の記録があります（実装済み・途中）。やり直すときは /na-go {n} force、"
                               f"レビューの戻りは /na-next {n}（ct-pr-turn）")
        if i["slot"] is not None and slot is not None and slot != i["slot"]:
            return False, f"#{n} は [{i['slot']}] で作業中です（1チケット1枠）。枠を変えるときはその枠を /clear してから指定してください"
        use = i["slot"] if i["slot"] is not None else (slot if slot is not None else free_slot(
            [x for x in watch_cache.get("items", []) if x["id"] != n], slots,
            {"tickets": {k: v for k, v in auto.get("tickets", {}).items() if k != n}}, "fix"))
        if use is None:
            return False, "空いている Claude の枠（環境1・2）がありません。枠を指定してください（/na-go 番号 枠）"
        # 同じ環境のもう一方の Claude の枠は同じリポジトリを使う。動いている作業があればブランチの切り替えで壊すので止める
        me = next((s for s in slots if s["slot"] == use), None)
        sib = [s for s in slots if me and s["env"] == me["env"] and s["slot"] != use and s["kind"] == "claude" and s["state"] in ("busy", "wait")]
        if sib:
            return False, (f"[{use}] と同じ {me['env']} の [{sib[0]['slot']}] が {WATCH_STATE_LABEL.get(sib[0]['state'], sib[0]['state'])}"
                           f"（#{sib[0].get('ticket') or '番号なし'}）です。同じリポジトリのブランチを切り替えるので、終わってから始めてください")
        text = GO_TEXT1.format(n=n, branch=branch)
        if dry:
            return True, f"🧪 dry-run: [{use}] ← {text[:90]}…（ct-ship-loop が終わったら ct-finish を自動で頼む）"
        ok, msg = na_to_send(use, text)
        last = i.get("last_flow") or {}
        _auto_record(auto, n, use, "ct-ship-loop", text, ok, msg, f"{last.get('skill')}@{int(last.get('end') or 0)}")
        if ok:
            t = auto["tickets"][n]
            t["slot"] = use
            t["go"] = {"stage": "ship-loop", "at": time.time(), "slot": use, "branch": branch}
        _json_save(HUB_AUTO, auto)
    if ok:
        return True, f"{msg}（{branch}。ct-ship-loop が終わったら ct-finish を自動で頼みます）"
    return False, msg


def go_step(auto, i, t):
    """autopilot から: /na-go したチケットの ct-ship-loop が終わったら ct-finish を頼み、ct-finish が終わったら完了にする。
    送ったら True（1回に1件）。"""
    g = t.get("go") or {}
    if g.get("stage") not in GO_ACTIVE or i["state"] != "next" or i["slot"] is None:
        return None
    last = i.get("last_flow") or {}
    if last.get("result") != "done" or (last.get("end") or 0) < g.get("at", 0):
        return None
    n = i["id"]
    if g["stage"] == "ship-loop" and last.get("skill") == "ct-ship-loop":
        text = GO_TEXT2.format(n=n)
        ok, msg = na_to_send(i["slot"], text)
        _auto_record(auto, n, i["slot"], "ct-finish", text, ok, msg)
        if ok:
            g.update(stage="finish", at=time.time())
            return True
        auto_fail(n, f"[{i['slot']}] に ct-finish を送れません: {msg}", f"go-finish@{int(last.get('end') or 0)}")
        return False
    if g["stage"] == "finish" and last.get("skill") == "ct-finish":
        g.update(stage="done", at=time.time())
        tmux_notify(f"✅ #{n} 実装と仕上げ（ct-finish）が終わりました。[{i['slot']}] で結果を確認してください")
        slack_dm(f"hub 監視\n✅ #{n} 実装と仕上げ（ct-finish）が終わりました。[{i['slot']}] で結果を確認してください（push はしていません）")
        return False
    return None


# E: 開発用サーバーの順番待ち（hub/bin/hub_docker.py が docker.json を読み書きする）。ここは「譲る」だけを受け持つ
HUB_DOCKER = os.path.join(HUB_STATE_DIR, "docker.json")
HUB_DOCKER_LOCK = os.path.join(HUB_STATE_DIR, "docker.lock")
DOCKER_YIELD = 30 * 60      # 使用中のチケットの枠がこの秒数止まって（質問・入力待ち）いて、待っている人がいれば譲る
DOCKER_QUEUE_STALE = 300    # hub_docker.py の QUEUE_STALE と同じ


def docker_check(slots):
    """使用中のチケットの枠が 30 分止まっていて、待っている人がいれば使用中を外す（次の人の wait が切り替える）。docker.json の要約を返す。"""
    try:
        os.makedirs(HUB_STATE_DIR, exist_ok=True)
        lf = open(HUB_DOCKER_LOCK, "a")
    except OSError:
        return None
    yielded = None
    with lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            d = _json_load(HUB_DOCKER, None)
            if not d:
                return {"holder": None, "queue": []}
            now = time.time()
            h = d.get("holder")
            queue = [q for q in d.get("queue") or [] if now - q.get("seen", 0) < DOCKER_QUEUE_STALE]
            changed = False
            if h:
                mine = [s for s in slots if s["kind"] == "claude" and s["env"] == h["env"] and s["state"] != "stopped"
                        and h["ticket"] in (s.get("tickets") or [s.get("ticket")])]
                if any(s["state"] == "busy" for s in mine):
                    if h.get("idle_since"):
                        h.pop("idle_since")
                        changed = True
                elif not h.get("idle_since"):
                    h["idle_since"] = now
                    changed = True
                elif queue and now - h["idle_since"] >= DOCKER_YIELD:
                    order = {str(x): k for k, x in enumerate(watch_order())}
                    nxt = sorted(queue, key=lambda q: (order.get(q["ticket"], 10_000), q["since"]))[0]
                    why = "枠が見つからない" if not mine else f"[{mine[0]['slot']}] が{WATCH_STATE_LABEL.get(mine[0]['state'], mine[0]['state'])}"
                    why += f"のまま {int((now - h['idle_since']) // 60)} 分"
                    d.setdefault("log", []).append({"at": now, "event": "yield", "ticket": h["ticket"], "env": h["env"], "to": nxt["ticket"], "why": why})
                    del d["log"][:-50]
                    d["holder"] = None
                    yielded = (h, nxt, why)
                    changed = True
            if changed:
                _json_save(HUB_DOCKER, d)
            summary = {"holder": d.get("holder"), "queue": queue}
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
    if yielded:
        h, nxt, why = yielded
        msg = (f"⏭ 開発用サーバーを #{h['ticket']}（{h['env']}）から #{nxt['ticket']}（{nxt['env']}）に譲りました（{why}）。"
               f"#{h['ticket']} は次にサーバーを使う前に hub_docker.py wait で並び直します")
        tmux_notify(msg[:150])
        slack_dm("hub 監視\n" + msg)
    return summary


def review_notify(fv_items, order):
    """F: 固定していないチケットのレビュー依頼・戻りを知らせる（固定したものは watch_notify と自動の依頼で扱う）。"""
    state = _json_load(HUB_NOTIFY + ".reviews", None)
    first = state is None
    state = state or {}
    now, msgs = {}, []
    for f in fv_items:
        n = str(f["id"])
        b = f.get("ball") or {}
        if b.get("kind") not in ("review_in", "fix") or n in order:
            continue
        key = b["kind"] + ":" + b.get("why", "")
        now[n] = key
        if not first and state.get(n) != key:
            msgs.append(f"#{n} {b.get('label')}（{b.get('why', '')[:60]}）— /na-order で順番に入れると ct-pr-turn を自動で頼みます")
    try:
        _json_save(HUB_NOTIFY + ".reviews", now)
    except OSError:
        pass
    if msgs:
        tmux_notify(" / ".join(m.split("—")[0] for m in msgs))
        slack_dm("hub 監視\n" + "\n".join(msgs))
    return msgs


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
        # Edge の拡張機能への合図のページ（合言葉なし。秘密は載せない）。Windows の Chrome が microsoft-edge: で Edge に開かせる。
        # edge-ext/ を入れていないときは、このページが自分で URL を開く
        ip = self.client_address[0].removeprefix("::ffff:")
        allow = load_config()["allow_ips"]
        if urlsplit(self.path).path == "/tabgroup" and ("*" in allow or ip in allow):
            body = TABGROUP_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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
        elif self.path == "/edge-ext.zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for f in sorted(os.listdir(os.path.join(BASE, "edge-ext"))):
                    z.write(os.path.join(BASE, "edge-ext", f), f)  # 展開したフォルダの直下に manifest.json が来るように
            body = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="edge-ext.zip"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/sys":
            self.send_json(sys_usage())
        elif self.path == "/api/memo":
            self.send_json(memo_read())
        elif self.path == "/api/pane":
            try:
                n = int(self.query.get("slot", ["0"])[0])
            except ValueError:
                n = 0
            if not 0 <= n <= 12:  # 0 は MAIN（hub）
                return self.send_json({"error": "slot は 0（MAIN）〜12 です"}, 400)
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
        elif self.path == "/api/watch":
            only = self.query.get("tickets", [""])[0]
            if only:  # 確かめる用: 固定の順を使わず、指定した番号で判定する（記録・通知はしない）
                scan_watch_skills()
                d = watch_build([t for t in re.findall(r"\d{4,6}", only)])
                d.pop("_fv", None), d.pop("_slots", None)
                self.send_json(d)
            elif self.query.get("refresh", [""])[0] == "1" or not watch_cache["at"]:
                self.send_json(watch_once())
            else:
                self.send_json(watch_cache)
        elif self.path == "/api/commands":
            self.send_json(command_list())
        elif self.path == "/api/skills":
            self.send_json({"skills": skill_list()})
        elif self.path == "/api/nippo":
            date = self.query.get("date", ["today"])[0]
            if date != "today" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                return self.send_json({"error": "date が不正です"}, 400)
            self.send_json(*nippo_view(date))
        elif self.path == "/api/nippo/prev":
            date = self.query.get("date", ["today"])[0]
            if date != "today" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                return self.send_json({"error": "date が不正です"}, 400)
            self.send_json(*nippo_prev(date))
        elif self.path == "/api/pane-label/history":
            n = self.query.get("slot", [""])[0]
            if not re.fullmatch(r"\d{1,2}", n):
                return self.send_json({"error": "slot が不正です"}, 400)
            self.send_json({"items": label_history(n)})
        elif self.path == "/api/link-title":
            self.send_json(*link_title(self.query.get("u", [""])[0]))
        elif self.path == "/api/redmine/issue":
            n = self.query.get("ticket", [""])[0]
            if not re.fullmatch(r"\d{4,6}", n):
                return self.send_json({"error": "ticket が不正です"}, 400)
            self.send_json(*redmine_issue(n))
        elif self.path == "/api/redmine/statuses":
            n = self.query.get("ticket", [""])[0]
            if not re.fullmatch(r"\d{1,7}", n):
                return self.send_json({"error": "ticket が不正です"}, 400)
            self.send_json(*redmine_statuses(n))
        elif self.path == "/api/history":
            n = self.query.get("ticket", [""])[0]
            if not re.fullmatch(r"\d{4,6}", n):
                return self.send_json({"error": "ticket が不正です"}, 400)
            self.send_json(history_full(n))
        elif self.path == "/api/panes":
            self.send_json(ai_panes())
        elif self.path == "/api/focus":
            n = self.query.get("ticket", [""])[0]
            if n and not re.fullmatch(r"\d{4,6}", n):
                return self.send_json({"error": "ticket が不正です"}, 400)
            self.send_json(focus_view(n or None, fresh=bool(n) and self.query.get("fresh", [""])[0] == "1"))
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
        if self.path == "/api/memo":
            text = req.get("text")
            if not isinstance(text, str) or len(text) > MEMO_MAX:
                return self.send_json({"error": f"メモは {MEMO_MAX:,} 文字までです"}, 400)
            base = req.get("base")
            try:
                base = None if req.get("force") else float(base or 0)
            except (TypeError, ValueError):
                return self.send_json({"error": "base が不正です"}, 400)
            body, code = memo_write(text, base)
            return self.send_json(body, code)
        if self.path == "/api/pane-label":
            try:
                slot = int(req.get("slot"))
            except (TypeError, ValueError):
                return self.send_json({"error": "slot が不正です"}, 400)
            label = re.sub(r"\s+", " ", str(req.get("label") or "")).strip()
            p = slot_pane(slot) if 0 <= slot <= 12 else None  # 0 は MAIN（hub）
            if not p:
                return self.send_json({"error": f"[{slot}] の枠が見つかりません"}, 404)
            set_pane_label(p["id"], label)
            remember_label(slot, label[:LABEL_MAX])
            return self.send_json({"ok": True, "label": label[:LABEL_MAX]})
        if self.path == "/api/watch/go":
            try:
                n = str(int(req.get("ticket")))
                slot = int(req["slot"]) if req.get("slot") not in (None, "") else None
            except (TypeError, ValueError):
                return self.send_json({"error": "ticket / slot が不正です"}, 400)
            if slot is not None and (slot % 2 == 0 or not 1 <= slot <= 11):
                return self.send_json({"ok": False, "msg": "枠は Claude の枠（奇数 1〜11）を指定してください"})
            ok, msg = auto_go(n, slot, str(req.get("branch") or ""), bool(req.get("force")), bool(req.get("dry")))
            return self.send_json({"ok": ok, "msg": msg})
        if self.path == "/api/watch/next":
            try:
                n = str(int(req.get("ticket")))
                slot = int(req["slot"]) if req.get("slot") not in (None, "") else None
            except (TypeError, ValueError):
                return self.send_json({"error": "ticket / slot が不正です"}, 400)
            if slot is not None and (slot % 2 == 0 or not 1 <= slot <= 11):
                return self.send_json({"ok": False, "msg": "枠は Claude の枠（奇数 1〜11）を指定してください"})
            ok, msg = auto_start(n, slot, bool(req.get("sweep")), bool(req.get("scope")), bool(req.get("dry")))
            return self.send_json({"ok": ok, "msg": msg})
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
        if self.path == "/api/send":
            try:
                slot = int(req.get("slot"))
            except (TypeError, ValueError):
                return self.send_json({"error": "slot が不正です"}, 400)
            cmd, tickets = str(req.get("cmd") or ""), req.get("tickets")
            if not 0 <= slot <= 12:  # 0 は MAIN（hub）
                return self.send_json({"error": "slot は 0（MAIN）〜12 です"}, 400)
            # 自由な文: 1行にそろえ（改行・タブは空白）、制御文字は落とす。1000 文字まで
            free = re.sub(r"[\x00-\x1f\x7f]", "", re.sub(r"[\r\n\t]+", " ", str(req.get("free") or ""))).strip()
            if len(free) > 1000:
                return self.send_json({"error": "自由入力は 1000 文字までです"}, 400)
            if cmd and not SEND_CMD.fullmatch(cmd):
                return self.send_json({"error": "コマンドは /ct-redmine のような形（/ と英小文字・数字・-）だけです"}, 400)
            if not cmd and not free:
                return self.send_json({"error": "コマンドか自由入力のどちらかを入れてください"}, 400)
            if not isinstance(tickets, list) or len(tickets) > 20 or not all(re.fullmatch(r"\d{4,6}", str(t)) for t in tickets):
                return self.send_json({"error": "チケット番号（4〜6桁）は 20 件までです"}, 400)
            launch = req.get("launch")
            if launch is not None:
                launch = (launch.get("kind"), launch.get("mode")) if isinstance(launch, dict) else (None, None)
                if launch[1] not in CLI_MODES.get(launch[0], {}):
                    return self.send_json({"error": "起動する CLI の指定が不正です"}, 400)
            if not cli_lock.acquire(blocking=False):  # 同じ枠に重ねて打たないよう、起動・停止・送信は1つずつ
                return self.send_json({"error": "別の起動・停止・送信を実行中です"}, 409)
            try:
                body, code = slot_send(slot, cmd, [str(t) for t in tickets], launch, free)
            finally:
                cli_lock.release()
            return self.send_json(body, code)
        if self.path == "/api/nippo":
            date = req.get("date") or "today"
            if date != "today" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
                return self.send_json({"error": "date が不正です"}, 400)
            return self.send_json(*nippo_save(req))
        if self.path == "/api/redmine/status":
            try:
                ticket, status_id = int(req.get("ticket")), int(req.get("status_id"))
            except (TypeError, ValueError):
                return self.send_json({"error": "ticket / status_id が不正です"}, 400)
            if ticket <= 0 or status_id <= 0:
                return self.send_json({"error": "ticket / status_id が不正です"}, 400)
            return self.send_json(*redmine_set_status(ticket, status_id))
        if self.path == "/api/cli":
            try:
                slot = int(req.get("slot"))
            except (TypeError, ValueError):
                return self.send_json({"error": "slot が不正です"}, 400)
            if not 0 <= slot <= 12:  # 0 は MAIN（hub）
                return self.send_json({"error": "slot は 0（MAIN）〜12 です"}, 400)
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
    threading.Thread(target=cpu_loop, daemon=True).start()
    threading.Thread(target=links_loop, daemon=True).start()
    load_artifacts()
    threading.Thread(target=artifacts_loop, daemon=True).start()
    threading.Thread(target=history_loop, daemon=True).start()
    threading.Thread(target=pane_label_loop, daemon=True).start()
    threading.Thread(target=today_loop, daemon=True).start()
    threading.Thread(target=pr_loop, daemon=True).start()
    threading.Thread(target=watch_loop, daemon=True).start()
    httpd = ThreadingHTTPServer((cfg["bind"], cfg["port"]), Handler)
    print(f"dev-dashboard: {cfg['bind']}:{cfg['port']} 許可: {', '.join(cfg['allow_ips'])}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
