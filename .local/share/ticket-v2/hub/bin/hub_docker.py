#!/usr/bin/env python3
"""開発用サーバー（Docker）の順番待ち（hub の E。2026-11-25〜）。

メモリの都合で、ローカルの開発用サーバー（api・app・sqs）は同時に1環境だけ動かす。テスト・ブラウザでの確認など、
ローカルの DB・Redis・サーバーが要る作業の前に各環境の Claude が `wait`、終わったら `release` する。
コードを書く・読むだけの作業は待たない（2026-11-25 設計: コード書きは並行、テストとブラウザ確認だけ順番待ち）。

  python3 hub_docker.py wait <番号> [--env envN] [--timeout 秒]  … 順番が来るまで待ち、来たら他の環境のサーバーを止めて自分の環境を起動する
                                                                     終了コード 0 = 使ってよい / 3 = まだ順番待ち（もう一度 wait）/ 1 = 失敗
  python3 hub_docker.py release <番号>                            … 使い終わった（サーバーは止めない。次の人の wait が切り替える）
  python3 hub_docker.py status                                    … 使用中・順番待ち・サーバーの状態

- 順番: hub の /na-order の順（固定したチケットが先、上が先）。固定していないものはその後に来た順
- 同じチケットがもう一度 wait しても、使用中ならそのまま使える（テストの前に毎回 wait してよい）
- 使用中のチケットの枠が 30 分止まって（質問・入力待ち）いて、待っている人がいれば、開発ダッシュボードの常駐ループが
  次の人に譲り、tmux と Slack DM で知らせる（譲られた側は次にサーバーを使う前に wait し直す）
- 待ちをやめた（wait を5分呼び直さない）待ちは順番から外す
- 環境は今いるフォルダ（~/www/ticket_v2 = env1・_second = env2・_third = env3・_fourth = env4）から判定する
"""
import fcntl
import json
import os
import subprocess
import sys
import time

sys.dont_write_bytecode = True

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(HUB, "docker.json")
LOCK = os.path.join(HUB, "docker.lock")
ORDER = os.path.join(HUB, "order.json")
LOCAL_SERVER = os.path.expanduser("~/bin/local-server")
ENV_DIRS = [("ticket_v2_second", "env2"), ("ticket_v2_third", "env3"), ("ticket_v2_fourth", "env4"), ("ticket_v2", "env1")]
QUEUE_STALE = 300   # この秒数 wait を呼び直さない待ちは外す
POLL = 10
ENVS = ("env1", "env2", "env3", "env4")


def env_of_cwd(cwd=None):
    cwd = os.path.realpath(cwd or os.getcwd())
    base = os.path.realpath(os.path.expanduser("~/www"))
    for name, env in ENV_DIRS:
        d = os.path.join(base, name)
        if cwd == d or cwd.startswith(d + "/"):
            return env
    return ""


class Locked:
    """docker.json の読み書きを1プロセスずつにする（各環境の Claude とダッシュボードが同時に触る）。"""

    def __enter__(self):
        os.makedirs(HUB, exist_ok=True)
        self.f = open(LOCK, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        try:
            with open(STATE, encoding="utf-8") as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}
        self.d.setdefault("holder", None)
        self.d.setdefault("queue", [])
        self.d.setdefault("log", [])
        return self.d

    def __exit__(self, *exc):
        if exc[0] is None:
            tmp = STATE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, STATE)
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def log(d, event, **kw):
    d["log"].append({"at": time.time(), "event": event, **kw})
    del d["log"][:-50]


def order_index():
    try:
        with open(ORDER, encoding="utf-8") as f:
            return {str(n): i for i, n in enumerate(json.load(f).get("order") or [])}
    except (OSError, ValueError):
        return {}


def queue_sorted(d):
    idx = order_index()
    now = time.time()
    d["queue"] = [q for q in d["queue"] if now - q.get("seen", 0) < QUEUE_STALE]
    return sorted(d["queue"], key=lambda q: (idx.get(q["ticket"], 10_000), q["since"]))


def server_status():
    """{env: "up" | "partial" | "down"}"""
    try:
        out = subprocess.run([LOCAL_SERVER, "status", "all"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    st = {e: [] for e in ENVS}
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 2 and p[1] in st:
            st[p[1]].append(p[0] in ("●", "◐"))
    return {e: ("up" if v and all(v) else "partial" if any(v) else "down") for e, v in st.items()}


def switch_to(env):
    """自分の環境以外のサーバーを止め、自分の環境を起動する。(成功したか, 文)"""
    st = server_status()
    msgs = []
    for e, s in st.items():
        if e != env and s != "down":
            r = subprocess.run([LOCAL_SERVER, "down", e, "all"], capture_output=True, text=True, timeout=600)
            msgs.append(f"{e} を停止" + ("" if r.returncode == 0 else f"（失敗: {(r.stdout + r.stderr).strip()[-200:]}）"))
            if r.returncode != 0:
                return False, "・".join(msgs)
    if st.get(env) != "up":
        r = subprocess.run([LOCAL_SERVER, "up", env, "all"], capture_output=True, text=True, timeout=900)
        msgs.append(f"{env} を起動" + ("" if r.returncode == 0 else f"（失敗: {(r.stdout + r.stderr).strip()[-200:]}）"))
        if r.returncode != 0:
            return False, "・".join(msgs)
    else:
        msgs.append(f"{env} は起動済み")
    return True, "・".join(msgs)


def try_acquire(ticket, env, slot):
    """(granted, 文)。順番の先頭で、使用中がいなければ使用中になる。"""
    now = time.time()
    with Locked() as d:
        h = d["holder"]
        if h and h["ticket"] == ticket:
            if h["env"] != env:
                log(d, "env_change", ticket=ticket, env=env, old=h["env"])
                h["env"] = env
            h["seen"] = now
            d["queue"] = [q for q in d["queue"] if q["ticket"] != ticket]
            return True, "使用中のまま"
        q = next((q for q in d["queue"] if q["ticket"] == ticket), None)
        if q:
            q.update(seen=now, env=env, slot=slot)
        else:
            d["queue"].append({"ticket": ticket, "env": env, "slot": slot, "since": now, "seen": now})
            log(d, "enqueue", ticket=ticket, env=env)
        qs = queue_sorted(d)
        if not h and qs and qs[0]["ticket"] == ticket:
            d["queue"] = [x for x in d["queue"] if x["ticket"] != ticket]
            d["holder"] = {"ticket": ticket, "env": env, "slot": slot, "since": now, "seen": now}
            log(d, "acquire", ticket=ticket, env=env)
            return True, "順番が来ました"
        pos = [x["ticket"] for x in qs].index(ticket) + 1
        using = f"使用中 #{h['ticket']}（{h['env']}）" if h else "空き（先に待っている人がいます）"
        return False, f"順番待ち {pos} 番目・{using}"


def cmd_wait(ticket, env, timeout, slot=None):
    if not env:
        print("⛔ 環境が分かりません（~/www/ticket_v2* の中で実行するか --env envN を付けてください）")
        return 1
    start, last = time.time(), ""
    while True:
        ok, msg = try_acquire(ticket, env, slot)
        if ok:
            sw_ok, sw = switch_to(env)
            if not sw_ok:
                with Locked() as d:
                    log(d, "switch_failed", ticket=ticket, env=env, msg=sw)
                print(f"⛔ 順番は来ましたが、サーバーの切り替えに失敗しました: {sw}（使用中のままです。直したら wait をやり直すか release）")
                return 1
            print(f"✅ 開発用サーバーを使ってよい: #{ticket} {env}（{msg}・{sw}）。終わったら hub_docker.py release {ticket}")
            return 0
        if msg != last:
            print(f"⏳ #{ticket} {env}: {msg}", flush=True)
            last = msg
        if time.time() - start >= timeout:
            print(f"⏳ まだ順番待ちです（{msg}）。もう一度 hub_docker.py wait {ticket} を実行してください（5分呼び直さないと順番から外れます）")
            return 3
        time.sleep(POLL)


def cmd_release(ticket):
    with Locked() as d:
        h = d["holder"]
        d["queue"] = [q for q in d["queue"] if q["ticket"] != ticket]
        if h and h["ticket"] == ticket:
            d["holder"] = None
            log(d, "release", ticket=ticket, env=h["env"], used=int(time.time() - h["since"]))
            print(f"✅ #{ticket} の使用を終えました（{h['env']} のサーバーは止めていません。次の人の wait が切り替えます）")
        else:
            print(f"#{ticket} は使用中ではありません（使用中: {('#' + h['ticket']) if h else 'なし'}）。順番待ちからは外しました")
    return 0


def cmd_status():
    with Locked() as d:
        h, qs = d["holder"], queue_sorted(d)
        recent = [x for x in d["log"] if x["event"] == "yield"][-3:]
    out = ["使用中: " + (f"#{h['ticket']} {h['env']}（{time.strftime('%H:%M', time.localtime(h['since']))}〜）" if h else "なし")]
    out.append("順番待ち: " + (" → ".join(f"#{q['ticket']}（{q['env']}）" for q in qs) if qs else "なし"))
    st = server_status()
    out.append("サーバー: " + " ".join(f"{e}={'●' if s == 'up' else '◐' if s == 'partial' else '○'}" for e, s in st.items()))
    for y in recent:
        out.append(f"譲った: {time.strftime('%m/%d %H:%M', time.localtime(y['at']))} #{y['ticket']} → #{y.get('to', '?')}（{y.get('why', '')}）")
    print("\n".join(out))
    return 0


def main(argv):
    if not argv or argv[0] not in ("wait", "release", "status"):
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    env, timeout, slot, args = "", 540, None, []
    it = iter(rest)
    for a in it:
        if a == "--env":
            env = next(it, "")
        elif a == "--timeout":
            timeout = int(next(it, "540"))
        elif a == "--slot":
            slot = int(next(it, "0")) or None
        else:
            args.append(a.lstrip("#"))
    if cmd == "status":
        return cmd_status()
    if len(args) != 1 or not args[0].isdigit():
        print(f"⛔ 書き方: hub_docker.py {cmd} <チケット番号>")
        return 1
    if cmd == "release":
        return cmd_release(args[0])
    if env and env not in ENVS:
        print(f"⛔ --env は {'/'.join(ENVS)} のどれかです")
        return 1
    return cmd_wait(args[0], env or env_of_cwd(), timeout, slot)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
