#!/usr/bin/env python3
"""開発用サーバー（Docker）の順番待ち（hub の E。2026-11-25〜。2026-11-27 同時に2環境まで＋重い処理の独占）。

メモリの都合で、ローカルの開発用サーバー（api・app・sqs）は同時に2環境まで動かす。テスト・ブラウザでの確認など、
ローカルの DB・Redis・サーバーが要る作業の前に各環境の Claude が `wait`、終わったら `release` する。
コードを書く・読むだけの作業は待たない（2026-11-25 設計: コード書きは並行、テストとブラウザ確認だけ順番待ち）。

重い処理（rspec・vitest・tsc（typecheck）・全ファイルの lint）は、前に `heavy start`、後に `heavy end` を必ず呼ぶ。
重い処理の間は、もう片方の環境はサーバーを使う操作（画面・rails runner・curl・テスト・lint）を一切止めて待つ
（もう片方の `wait` は重い処理が終わるまで返らない。コードの編集・読むことは続けてよい）。重い処理は同時に1つだけ。
変更ファイルだけの rubocop・eslint は重い処理に入れない（2026-11-27 ユーザー「同時に2台まで・rspec や vitest の間はもう片方は止める」）。
2台目を起動するとき・重い処理を始めるときは、Mac のメモリの圧迫レベルが危険（4）なら始めずに待つ（ブレーキ）。

  python3 hub_docker.py wait <番号> [--env envN] [--timeout 秒]  … 順番が来るまで待ち、来たら使用中でない環境のサーバーを止めて自分の環境を起動する
                                                                     終了コード 0 = 使ってよい / 3 = まだ順番待ち（もう一度 wait）/ 1 = 失敗
  python3 hub_docker.py heavy start <番号> [--what rspec] [--timeout 秒] … 重い処理を始める（使用中であること。もう片方の重い処理・メモリの危険を待つ）
                                                                     終了コード 0 = 始めてよい / 3 = まだ待ち（もう一度）/ 1 = 失敗（使用中でない等）
  python3 hub_docker.py heavy end <番号>                          … 重い処理を終えた（失敗・中断でも必ず呼ぶ。40 分呼ばなければ自動で外す）
  python3 hub_docker.py release <番号>                            … 使い終わった（サーバーは止めない。次の人の wait が切り替える。重い処理も外す）
  python3 hub_docker.py status                                    … 使用中・順番待ち・サーバーの状態（hub の /na-server-status は report() で詳しく出す）

- 順番: hub の /na-order の順（固定したチケットが先、上が先）。固定していないものはその後に来た順
- 同じチケットがもう一度 wait しても、使用中ならそのまま使える（テストの前に毎回 wait してよい）
- 使用中のチケットの枠が 15 分止まって（質問・入力待ち）いるか、45 分 wait を呼んでいない（処理中でも）とき、待っている人がいれば、
  開発ダッシュボードの常駐ループが次の人に譲り、tmux と Slack DM と使用中だった枠に知らせる（譲られた側は次にサーバーを使う前に wait し直す）
- 待ちをやめた（wait を5分呼び直さない）待ちは順番から外す
- 環境は今いるフォルダ（~/www/ticket_v2 = env1・_second = env2・_third = env3・_fourth = env4・_fifth = env5・_sixth = env6）から判定する
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
ENV_DIRS = [("ticket_v2_second", "env2"), ("ticket_v2_third", "env3"), ("ticket_v2_fourth", "env4"),
            ("ticket_v2_fifth", "env5"), ("ticket_v2_sixth", "env6"), ("ticket_v2", "env1")]
QUEUE_STALE = 300   # この秒数 wait を呼び直さない待ちは外す
POLL = 10
MAX_HOLDERS = 2      # 同時に使用中にできる環境の数（2026-11-27 1→2）
HEAVY_STALE = 40 * 60  # 重い処理の印をこの秒数 heavy start / wait で更新しなければ外す（end の呼び忘れ）
# メモリのブレーキ: Mac の kern.memorystatus_vm_pressure_level（1 正常・2 警告・4 危険）がこれ以上なら、2台目の起動・重い処理を始めない。
# 警告（2）は Docker に 12.5GB を割り当てている都合で1台でも常に出ている（2026-11-27 実測）ため、危険（4）にした
MEM_BRAKE_LEVEL = 4
ENVS = ("env1", "env2", "env3", "env4", "env5", "env6")


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
        self.d.setdefault("queue", [])
        self.d.setdefault("log", [])
        self.d.setdefault("heavy", None)
        hs = self.d.setdefault("holders", [])
        old = self.d.get("holder")  # 2026-11-27 より前の形（1人）・古い wait のプロセスが書いたもの
        if old and not any(h["ticket"] == old["ticket"] for h in hs):
            hs.append(old)
        return self.d

    def __exit__(self, *exc):
        if exc[0] is None:
            self.d["holder"] = self.d["holders"][0] if self.d["holders"] else None  # 古い形を読む wait のプロセス向け（先頭だけ）
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


def mem_level():
    """Mac のメモリの圧迫レベル（1 正常・2 警告・4 危険）。取れなければ 1。"""
    try:
        return int(subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True, text=True, timeout=5).stdout.strip() or 1)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 1


MEM_LABEL = {1: "正常", 2: "警告", 4: "危険"}


def heavy_live(d, now=None):
    """有効な重い処理の印（古いものは外す）。"""
    hv = d.get("heavy")
    now = now or time.time()
    if hv and (now - hv.get("seen", hv["since"]) >= HEAVY_STALE or not any(h["ticket"] == hv["ticket"] for h in d["holders"])):
        log(d, "heavy_stale", ticket=hv["ticket"], env=hv.get("env", ""))
        d["heavy"] = hv = None
    return hv


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


def switch_to(env, keep=()):
    """使用中でない環境（keep 以外）のサーバーを止め、自分の環境を起動する。(成功したか, 文)"""
    st = server_status()
    msgs = []
    for e, s in st.items():
        if e != env and e not in keep and s != "down":
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


def holders_text(d):
    return "・".join(f"#{h['ticket']}（{h['env']}）" for h in d["holders"]) or "なし"


def try_acquire(ticket, env, slot):
    """(granted, 文, 他の使用中の環境)。順番の先頭で、使用中が2環境未満なら使用中になる。
    重い処理（他のチケット）の間は、使用中でも「待て」を返す（もう片方は操作を止める）。"""
    now = time.time()
    with Locked() as d:
        hv = heavy_live(d, now)
        h = next((x for x in d["holders"] if x["ticket"] == ticket), None)
        others = [x["env"] for x in d["holders"] if x["ticket"] != ticket]
        if h:
            if h["env"] != env:
                log(d, "env_change", ticket=ticket, env=env, old=h["env"])
                h["env"] = env
            h["seen"] = now
            d["queue"] = [q for q in d["queue"] if q["ticket"] != ticket]
            if hv and hv["ticket"] != ticket:
                return False, f"使用中のまま・重い処理（#{hv['ticket']} {hv['env']} {hv.get('what', '')}）の終わりを待っています。サーバーを使う操作は止めてください", others
            return True, "使用中のまま", others
        q = next((q for q in d["queue"] if q["ticket"] == ticket), None)
        if q:
            q.update(seen=now, env=env, slot=slot)
        else:
            d["queue"].append({"ticket": ticket, "env": env, "slot": slot, "since": now, "seen": now})
            log(d, "enqueue", ticket=ticket, env=env)
        qs = queue_sorted(d)
        pos = [x["ticket"] for x in qs].index(ticket) + 1
        using = f"使用中 {holders_text(d)}"
        if len(d["holders"]) < MAX_HOLDERS and qs and qs[0]["ticket"] == ticket:
            if hv:
                return False, f"順番待ち {pos} 番目・{using}・重い処理（#{hv['ticket']} {hv.get('what', '')}）の終わりを待っています", others
            lv = mem_level() if d["holders"] else 1
            if lv >= MEM_BRAKE_LEVEL:
                return False, f"順番待ち {pos} 番目・{using}・メモリが{MEM_LABEL.get(lv, lv)}なので2台目を起動しません", others
            d["queue"] = [x for x in d["queue"] if x["ticket"] != ticket]
            d["holders"].append({"ticket": ticket, "env": env, "slot": slot, "since": now, "seen": now})
            log(d, "acquire", ticket=ticket, env=env)
            return True, "順番が来ました", others
        return False, f"順番待ち {pos} 番目・{using}", others


def cmd_wait(ticket, env, timeout, slot=None):
    if not env:
        print("⛔ 環境が分かりません（~/www/ticket_v2* の中で実行するか --env envN を付けてください）")
        return 1
    start, last = time.time(), ""
    while True:
        ok, msg, others = try_acquire(ticket, env, slot)
        if ok:
            sw_ok, sw = switch_to(env, keep=others)
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
        h = next((x for x in d["holders"] if x["ticket"] == ticket), None)
        d["queue"] = [q for q in d["queue"] if q["ticket"] != ticket]
        if (d.get("heavy") or {}).get("ticket") == ticket:
            log(d, "heavy_end", ticket=ticket, env=d["heavy"].get("env", ""), why="release")
            d["heavy"] = None
        if h:
            d["holders"] = [x for x in d["holders"] if x["ticket"] != ticket]
            log(d, "release", ticket=ticket, env=h["env"], used=int(time.time() - h["since"]))
            print(f"✅ #{ticket} の使用を終えました（{h['env']} のサーバーは止めていません。次の人の wait が切り替えます）")
        else:
            print(f"#{ticket} は使用中ではありません（使用中: {holders_text(d)}）。順番待ちからは外しました")
    return 0


def cmd_heavy(sub, ticket, what, timeout):
    """重い処理の開始・終了。開始は「使用中であること・他の重い処理が無いこと・メモリが危険でないこと」を待つ。"""
    if sub == "end":
        with Locked() as d:
            hv = d.get("heavy")
            if hv and hv["ticket"] == ticket:
                d["heavy"] = None
                log(d, "heavy_end", ticket=ticket, env=hv.get("env", ""), used=int(time.time() - hv["since"]))
                print(f"✅ #{ticket} の重い処理を終えました（もう片方の環境はサーバーを使う操作を再開できます）")
            else:
                print(f"#{ticket} の重い処理の印はありません（今の重い処理: {('#' + hv['ticket']) if hv else 'なし'}）")
        return 0
    start, last = time.time(), ""
    while True:
        now = time.time()
        with Locked() as d:
            h = next((x for x in d["holders"] if x["ticket"] == ticket), None)
            if not h:
                print(f"⛔ #{ticket} は開発用サーバーの使用中ではありません。先に hub_docker.py wait {ticket}")
                return 1
            h["seen"] = now
            hv = heavy_live(d, now)
            others = [x for x in d["holders"] if x["ticket"] != ticket]
            lv = mem_level() if others else 1
            if hv and hv["ticket"] == ticket:
                hv.update(seen=now, what=what or hv.get("what", ""))
                msg = None
            elif hv:
                msg = f"重い処理 #{hv['ticket']}（{hv['env']} {hv.get('what', '')}）の終わりを待っています"
            elif lv >= MEM_BRAKE_LEVEL:
                msg = f"メモリが{MEM_LABEL.get(lv, lv)}なので待っています"
            else:
                d["heavy"] = {"ticket": ticket, "env": h["env"], "what": what, "since": now, "seen": now,
                              "others": [x["ticket"] for x in others]}
                log(d, "heavy_start", ticket=ticket, env=h["env"], what=what)
                msg = None
        if msg is None:
            stop = "・".join(f"#{x['ticket']}（{x['env']}）" for x in others)
            print(f"✅ 重い処理（{what or '指定なし'}）を始めてよい: #{ticket}。"
                  + (f"もう片方 {stop} はサーバーを使う操作を止めます（hub が知らせます）。" if stop else "")
                  + f"終わったら（失敗・中断でも）hub_docker.py heavy end {ticket}")
            return 0
        if msg != last:
            print(f"⏳ #{ticket}: {msg}", flush=True)
            last = msg
        if time.time() - start >= timeout:
            print(f"⏳ まだ始められません（{msg}）。もう一度 hub_docker.py heavy start {ticket} を実行してください")
            return 3
        time.sleep(POLL)


HOLD_STALE = 45 * 60  # server.py の DOCKER_HOLD_STALE と同じ（この秒数 wait を呼ばなければ、待っている人に譲る）
YIELD_IDLE = 15 * 60  # server.py の DOCKER_YIELD と同じ（使用中の枠がこの秒数止まっていれば譲る）
EVENT_LABEL = {"acquire": "使い始め", "release": "返した", "yield": "譲った", "enqueue": "並んだ", "env_change": "環境を変えた",
               "switch_failed": "切り替え失敗", "heavy_start": "重い処理を開始", "heavy_end": "重い処理を終了",
               "heavy_stale": "重い処理の印を外した（end なし）"}


def ago(sec):
    sec = max(0, int(sec))
    return f"{sec // 60} 分" if sec < 3600 else f"{sec // 3600} 時間 {sec % 3600 // 60} 分"


def report(detail=True, slots=None):
    """使用中・順番待ち・サーバー・直近の記録の文。slots: {チケット番号: "[1] 処理中"}（/na-server-status がダッシュボードから渡す）"""
    slots = slots or {}
    now = time.time()
    with Locked() as d:
        hs, qs, hv = list(d["holders"]), queue_sorted(d), heavy_live(d, now)
        logs = d["log"][-6:] if detail else [x for x in d["log"] if x["event"] == "yield"][-3:]
    out = []
    for h in hs:
        seen = now - h.get("seen", h["since"])
        out.append(f"使用中: #{h['ticket']} {h['env']} {slots.get(h['ticket'], '')}".rstrip()
                   + f"・{time.strftime('%H:%M', time.localtime(h['since']))}〜（{ago(now - h['since'])}）・最後の wait {ago(seen)}前")
        if qs and len(hs) >= MAX_HOLDERS:
            idle = h.get("idle_since")
            left = HOLD_STALE - seen
            why = [f"wait が無いまま あと {ago(left)} で譲る" if left > 0 else "wait が無いので次の判定で譲る"]
            if idle:
                why.append(f"枠が止まって {ago(now - idle)}（{ago(YIELD_IDLE)} で譲る）")
            out.append("  " + "・".join(why))
    if not hs:
        out.append("使用中: なし")
    out.append(f"  （同時に {MAX_HOLDERS} 環境まで・空き {MAX_HOLDERS - len(hs)}）")
    if hv:
        out.append(f"重い処理: #{hv['ticket']} {hv['env']} {hv.get('what', '')}・{ago(now - hv['since'])}前から（もう片方はサーバーを使う操作を止めて待つ）")
    lv = mem_level()
    out.append(f"メモリ: {MEM_LABEL.get(lv, lv)}（{MEM_LABEL.get(MEM_BRAKE_LEVEL)}で2台目・重い処理を止める）")
    if qs:
        out.append("順番待ち:")
        for k, q in enumerate(qs, 1):
            out.append(f"  {k}. #{q['ticket']} {q['env']} {slots.get(q['ticket'], '')}".rstrip() + f"・{ago(now - q['since'])}待ち")
    else:
        out.append("順番待ち: なし")
    st = server_status()
    mark = {"up": "● 起動", "partial": "◐ 一部", "down": "○ 停止"}
    out.append("サーバー: " + "　".join(f"{e} {mark.get(s, '?')}" for e, s in st.items()))
    if logs:
        out.append("直近の記録:" if detail else "")
        for y in logs:
            line = f"  {time.strftime('%m/%d %H:%M', time.localtime(y['at']))} #{y['ticket']} {y.get('env', '')} {EVENT_LABEL.get(y['event'], y['event'])}"
            if y["event"] == "yield":
                line += f" → #{y.get('to', '?')}（{y.get('why', '')}）"
            elif y["event"] == "heavy_start" and y.get("what"):
                line += f"（{y['what']}）"
            elif y["event"] in ("release", "heavy_end") and y.get("used"):
                line += f"（{ago(y['used'])}使用）"
            out.append(line)
    return "\n".join(x for x in out if x)


def cmd_status():
    print(report(detail=False))
    return 0


def main(argv):
    if not argv or argv[0] not in ("wait", "release", "status", "heavy"):
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    sub = ""
    if cmd == "heavy":
        if not rest or rest[0] not in ("start", "end"):
            print("⛔ 書き方: hub_docker.py heavy start|end <チケット番号> [--what rspec]")
            return 1
        sub, rest = rest[0], rest[1:]
    env, timeout, slot, what, args = "", 540, None, "", []
    it = iter(rest)
    for a in it:
        if a == "--env":
            env = next(it, "")
        elif a == "--timeout":
            timeout = int(next(it, "540"))
        elif a == "--what":
            what = next(it, "")
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
    if cmd == "heavy":
        return cmd_heavy(sub, args[0], what, timeout)
    if env and env not in ENVS:
        print(f"⛔ --env は {'/'.join(ENVS)} のどれかです")
        return 1
    return cmd_wait(args[0], env or env_of_cwd(), timeout, slot)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
