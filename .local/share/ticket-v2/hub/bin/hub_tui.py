#!/usr/bin/env python3
"""hub のポップアップの中で動く、操作できる一覧（/na-list・/na-watch・/na-redmine・/na-order）。

  python3 hub_tui.py list            /na-list    枠の一覧 → Enter でその枠の詳細
  python3 hub_tui.py slot 7 [行数]    /na-list 7  枠の詳細（画面の末尾）
  python3 hub_tui.py watch           /na-watch   固定したチケット → Enter でチケットと枠の詳細
  python3 hub_tui.py redmine [引数…]  /na-redmine 自分のチケット → Enter で詳細（o でブラウザ）
  python3 hub_tui.py order           /na-order   固定の順 → K J（Shift）で上下へ動かす・x で外す・Enter で詳細

一覧のキー: ↑↓ j k 選ぶ / → l 選んだ行を全文に広げる / ← h たたむ / a 全部広げる・たたむ / Enter 詳細 /
          o ブラウザで開く / r 取り直す（一覧は 15 秒ごとにも取り直す） / g G 先頭・末尾 / q Esc 閉じる
詳細のキー: ↑↓ PgUp PgDn スクロール / r 取り直す / o ブラウザ / Esc ← q 一覧へ戻る（長い行は折り返して全部出す）
"""
import os
import re
import subprocess
import sys
import termios
import time
import tty

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_pager as pg  # noqa: E402  （キーの読み取り・色付きの文の切り出し）
import hub_popup as hp  # noqa: E402  （色・幅・カードの部品）

c, dw, trim, pad = hp.c, hp.dw, hp.trim, hp.pad
SGR = re.compile(r"\x1b\[[0-9;]*m")
SEL = "\x1b[48;5;238m"
AUTO_RELOAD = 15


def cols_rows():
    s = os.get_terminal_size()
    return s.columns, s.lines


def wrap(line, width, indent=""):
    """色付きの1行を表示幅 width で折り返す（色は次の行へ引き継ぐ）。2行目からは indent を付ける"""
    out, cur, cw, active = [], "", 0, []
    for esc, ch in pg.TOKEN.findall(line):
        if esc:
            cur += esc
            active = [] if esc in ("\x1b[0m", "\x1b[m") else active + [esc]
            continue
        w = pg.cw(ch)
        if cw + w > width:
            out.append(cur + "\x1b[0m")
            cur, cw = indent + "".join(active), dw(indent)
        cur += ch
        cw += w
    out.append(cur + "\x1b[0m")
    return out


def run_cmd(cmd):
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


# ---- 画面の種類 ----------------------------------------------------------------------------------

class TextView:
    """スクロールする文（詳細）。load() → (見出し, 行の一覧, URL)"""
    auto = False

    def __init__(self, load):
        self.load_fn, self.top, self.title, self.lines, self.url = load, 0, "", [], ""
        self.reload()

    def reload(self):
        try:
            self.title, self.lines, self.url = self.load_fn()
        except (Exception, SystemExit) as e:  # 取れなくても画面は閉じない
            self.title, self.lines, self.url = "エラー", [c("red", f"⛔ 取得できませんでした: {type(e).__name__}: {e}")], ""

    def draw(self, cols, rows):
        body = []
        for ln in self.lines:
            body += wrap(ln, cols - 1, "    ")
        h = rows - 2
        self.top = max(0, min(self.top, len(body) - h))
        pos = f"{min(self.top + h, len(body))}/{len(body)} 行" if len(body) > h else "全体"
        keys = "Esc ← 戻る  ↑↓ スクロール  r 取り直す" + ("  o ブラウザ" if self.url else "")
        return [hp.header(self.title, "", cols - 1)] + body[self.top:self.top + h], f" {keys}   {pos}"

    def key(self, k, cols, rows):
        h = rows - 2
        self.top += {"UP": -1, "k": -1, "WHEELUP": -3, "DOWN": 1, "j": 1, "WHEELDN": 3, "PGUP": -h, "b": -h, "PGDN": h, " ": h}.get(k, 0)
        if k in ("HOME", "g"):
            self.top = 0
        elif k in ("END", "G"):
            self.top = 10 ** 6
        elif k == "r":
            self.reload()
        elif k == "o" and self.url:
            run_cmd(["open", self.url])
        elif k in ("ESC", "q", "LEFT", "h"):
            return "back"
        return None


class ListView:
    """選べる一覧。load() → (見出し, [項目])。項目: key・group（区切りの見出し）・row(width)→1行・full(width)→広げた行・enter()→画面・url"""
    auto = True

    def __init__(self, load, keys=None, foot=""):
        self.load_fn, self.sel, self.top, self.open, self.title, self.items = load, 0, 0, set(), "", []
        self.keys_fn, self.extra_foot = keys, foot  # keys(view, k) → True なら処理済み（一覧ごとの追加のキー）
        self.reload()

    def reload(self):
        key = self.items[self.sel]["key"] if self.items and self.sel < len(self.items) else None
        try:
            self.title, self.items = self.load_fn()
        except (Exception, SystemExit) as e:
            self.title, self.items = "エラー", [{"key": "err", "row": lambda w, e=e: c("red", f"⛔ 取得できませんでした: {type(e).__name__}: {e}"),
                                                 "full": lambda w: [], "enter": None, "url": ""}]
        keys = [i["key"] for i in self.items]
        self.sel = keys.index(key) if key in keys else min(self.sel, max(len(self.items) - 1, 0))
        self.loaded = time.time()

    def draw(self, cols, rows):
        lines, sel_at, group = [], (0, 0), None
        for n, it in enumerate(self.items):
            if it.get("group") and it["group"] != group:
                group = it["group"]
                lines += ([""] if lines else []) + ["  " + hp.rule(cols - 4, group)]
            start = len(lines)
            row = it["row"](cols - 5)
            mark = c("cyan", "▶ ") if n == self.sel else "  "
            line = " " + mark + row
            if n == self.sel:
                line = SEL + SGR.sub(lambda m: m.group(0) + SEL, line) + " " * max(cols - 1 - dw(line), 0) + "\x1b[0m"
            lines.append(line)
            if it["key"] in self.open:
                for fl in it["full"](cols - 8):
                    lines += [ln for ln in wrap("      " + fl, cols - 2, "      ")]
            if n == self.sel:
                sel_at = (start, len(lines))
        h = rows - 2
        if sel_at[0] < self.top:
            self.top = sel_at[0]
        elif sel_at[1] > self.top + h:
            self.top = min(sel_at[1] - h, sel_at[0])
        self.top = max(0, min(self.top, max(len(lines) - h, 0)))
        age = int(time.time() - self.loaded)
        foot = f" {self.extra_foot}  ↑↓ 選ぶ  → 全文  ← たたむ  a 全部  Enter 詳細  o ブラウザ  r 取り直す  q Esc 閉じる   {self.sel + 1}/{len(self.items)} 件・{age} 秒前"
        return [hp.header(self.title, "", cols - 1)] + lines[self.top:self.top + h], foot

    def key(self, k, cols, rows):
        if not self.items:
            return "back" if k in ("ESC", "q") else None
        it = self.items[self.sel]
        if self.keys_fn and self.keys_fn(self, k):
            return None
        step = {"UP": -1, "k": -1, "WHEELUP": -1, "DOWN": 1, "j": 1, "WHEELDN": 1, "PGUP": -10, "PGDN": 10}.get(k)
        if step:
            self.sel = max(0, min(self.sel + step, len(self.items) - 1))
        elif k in ("HOME", "g"):
            self.sel = 0
        elif k in ("END", "G"):
            self.sel = len(self.items) - 1
        elif k in ("RIGHT", "l"):
            self.open.add(it["key"])
        elif k in ("LEFT", "h"):
            self.open.discard(it["key"])
        elif k == "a":
            self.open = set() if self.open else {i["key"] for i in self.items}
        elif k == "r":
            self.reload()
        elif k == "o" and it.get("url"):
            run_cmd(["open", it["url"]])
        elif k in ("\r", "\n") and it.get("enter"):
            return it["enter"]()
        elif k in ("ESC", "q"):
            return "back"
        return None


# ---- /na-list -------------------------------------------------------------------------------------

def slot_view(slot, n=80):
    def load():
        text = hp.render_slot(slot, n)
        lines = text.split("\n")
        return f"[{slot}] の詳細", lines[2:] if len(lines) > 2 else lines, ""
    return TextView(load)


def list_view():
    import hub_status as hs

    def load():
        rows = [r for r in hs.collect("monitor") if r["slot"] % 2 == 1]
        items = []
        for r in rows:
            on = r["kind"] in ("claude", "codex")
            st = hp.short_state(r["state"])

            def row(w, r=r, st=st, on=on):
                if not on:
                    return c("dark", f"[{r['slot']}]".ljust(5) + " 未起動")
                head = BOLD(f"[{r['slot']}]".ljust(5)) + " " + pad(c(hp.state_color(st), st), 9) + " " \
                    + pad(f"#{r['ticket']}" if r.get("ticket") else c("dark", "—"), 7) + " " + pad(r["env"], 5) + " " \
                    + pad(trim(hs.short_branch(r["branch"]), 18), 18) + " " + pad(r["ctx"], 11) + " " + pad(r["done"] or c("dark", "—"), 6) + " "
                avail = max(w - dw(head), 10)
                if r.get("pending"):
                    return head + c("yellow", trim("未送信 " + re.sub(r"\s+", " ", r["pending"]), avail))
                return head + c("gray", trim(re.sub(r"\s+", " ", r["last"] or "").strip(), avail))

            def full(w, r=r):
                if not on:
                    return []
                out = [c("gray", "ブランチ ") + hs.short_branch(r["branch"])]
                if r.get("pending"):
                    out.append(c("yellow", "未送信 ") + r["pending"])
                out.append(c("gray", "最後の応答 ") + re.sub(r"\s+", " ", r["last"] or "").strip())
                return out

            items.append({"key": r["slot"], "row": row, "full": full, "url": "",
                          "enter": (lambda s=r["slot"]: slot_view(s)) if on else None})
        on = sum(1 for r in rows if r["kind"] in ("claude", "codex"))
        return f"枠（Claude）  起動 {on} · 未起動 {len(rows) - on}   {time.strftime('%H:%M')}", items
    return ListView(load)


def BOLD(s):
    return hp.BOLD + s + hp.RST


hp.width = lambda: cols_rows()[0] - 4  # ポップアップの中では端末の幅いっぱいに描く


# ---- /na-watch ------------------------------------------------------------------------------------

def ticket_detail(i_fn, slot):
    """チケットのカード（全文）＋ 枠があればその枠の詳細"""
    def load():
        import hub_watch as hw
        d = hw.fetch()
        i = next((x for x in d.get("items") or [] if str(x["id"]) == str(i_fn)), None)
        cols = cols_rows()[0] - 2
        lines = []
        if i:
            lines += hp.ticket_card(i, d, cols)
            a = (d.get("auto") or {}).get(i["id"]) or {}
            if (a.get("last") or {}).get("msg"):
                lines += ["", c("gray", "  自動の依頼の最後の結果 ") + a["last"]["msg"]]
            for lg in (a.get("log") or [])[-5:]:
                lines.append(c("dark", "  " + time.strftime("%m-%d %H:%M ", time.localtime(lg.get("at") or 0))) + lg.get("msg", ""))
        if slot is not None:
            t = hp.render_slot(slot, 60).split("\n")
            lines += ["", "  " + hp.rule(cols - 2, f"[{slot}] の枠")] + t[2:]
        return f"#{i_fn}", lines, (i or {}).get("url", "")
    return TextView(load)


def watch_view():
    import hub_watch as hw

    def load():
        d = hw.fetch()
        items = []
        for i in d.get("items") or []:
            def row(w, i=i):
                st = i.get("state_label", "")
                head = (c("red", "● ") if i.get("attention") else "  ") + BOLD(f"#{i['id']}") + " " \
                    + c(hp.PRIO_COLOR.get(i.get("priority"), "gray"), pad(i.get("priority") or "?", 6)) + " " \
                    + pad(f"[{i['slot']}]" if i.get("slot") is not None else "—", 4) + " " + pad(c(hp.state_color(st), trim(st, 14)), 14) + " " \
                    + pad(c("blue", (i.get("skill") or "").removeprefix("ct-")), 11) + " "
                return head + trim(i.get("subject", ""), max(w - dw(head), 10))

            def full(w, i=i):
                return hp.ticket_card(i, d, w)[1:]

            items.append({"key": str(i["id"]), "row": row, "full": full, "url": i.get("url", ""),
                          "enter": lambda i=i: ticket_detail(i["id"], i.get("slot"))})
        dk = d.get("docker") or {}
        srv = "開発用サーバー " + hp.docker_line(dk)
        return f"監視  {len(items)} 件 · 確認待ち {d.get('attention', 0)}   {srv}   {time.strftime('%H:%M')}", items
    return ListView(load)


# ---- /na-redmine ----------------------------------------------------------------------------------

def redmine_view(args):
    import hub_redmine as hr

    def load():
        limit, pris, refresh, _ = hr.parse_args(args)
        d = hr.fetch(refresh)
        if d.get("error"):
            raise RuntimeError(d["error"])
        pinned = hr.pinned_items(d)
        pin_ids = {i["id"] for i in pinned}
        ts = [i for i in hr.targets(d) if i["id"] not in pin_ids]
        ps = hr.default_pris(hr.targets(d)) if pris is None else (None if "*" in pris else pris)
        if ps:
            ts = [i for i in ts if i.get("priority") in ps]
        groups = [(0, pinned)] + [(t, sorted((i for i in ts if hr.tier(i) == t), key=hr.sort_key)) for t in (1, 2, 3)]
        items, left = [], limit or 10 ** 6
        for tno, g in groups:
            for i in g[:max(left, 0)]:
                items.append(redmine_item(i, hr.TIER_TITLE[tno] + f" {len(g)}件"))
            left -= len(g)
        filt = "/".join(p for p in reversed(hr.PRIORITIES) if p in ps) if ps else "全優先度"
        return f"Redmine  {len(items)} 件（{filt}）   {time.strftime('%H:%M')}", items
    return ListView(load)


# ---- /na-order -----------------------------------------------------------------------------------

def order_view():
    """固定の順。J K（Shift）で1つ上下へ動かす・x で外す（hub/order.json にすぐ保存）"""
    import hub_redmine as hr

    def load():
        d = hr.fetch()
        if d.get("error"):
            raise RuntimeError(d["error"])
        known = hr.known_issues(d)
        order = hr.load_order()
        items = []
        for k, n in enumerate(order, 1):
            i = known.get(n) or hr.fetch_issue(n)
            if i.get("error"):
                items.append({"key": str(n), "row": lambda w, k=k, e=i["error"]: f"{k:>2}. " + c("red", e),
                              "full": lambda w: [], "enter": None, "url": ""})
                continue
            it = redmine_item(i, "")
            row = it["row"]
            it["row"] = lambda w, k=k, row=row, out=(n not in known): c("cyan", f"{k:>2}. ") + row(w - 4 - (7 if out else 0)) + (c("gray", " [一覧外]") if out else "")
            items.append(it)
        if not items:
            items = [{"key": "none", "row": lambda w: c("gray", "固定の順: なし（/na-order 14926 14921 で、この順で /na-redmine の先頭に固定）"),
                      "full": lambda w: [], "enter": None, "url": ""}]
        return f"固定の順  {len(order)} 件（/na-redmine の先頭・/na-watch の監視対象）   {time.strftime('%H:%M')}", items

    def keys(v, k):
        order = hr.load_order()
        if not order or v.sel >= len(order) or v.items[v.sel]["key"] != str(order[v.sel]):
            return False
        n = order[v.sel]
        if k in ("K", "J"):
            to = v.sel + (-1 if k == "K" else 1)
            if 0 <= to < len(order):
                order.insert(to, order.pop(v.sel))
                hr.save_order(order)
                v.reload()
                v.sel = to
            return True
        if k == "x":
            hr.save_order([x for x in order if x != n])
            v.open.discard(str(n))
            v.reload()
            return True
        return False
    return ListView(load, keys, "K J 上下へ動かす  x 外す ")


def sessions_text(i):
    return " ".join(f"[{s['slot']}]{hp.short_state(hp_state(s.get('state')))}" + (f" {s['skill']}" if s.get("skill") else "")
                    for s in i.get("sessions") or [])


def hp_state(s):
    return {"busy": "x 処理中", "wait": "x 確認待ち", "idle": "x 入力待ち", "stopped": "x 停止"}.get(s, "x " + (s or ""))


def redmine_item(i, group):
    def row(w):
        head = BOLD(f"#{i['id']}") + " " + c(hp.PRIO_COLOR.get(i.get("priority"), "gray"), pad(i.get("priority") or "?", 6)) + " " \
            + pad(c("gray", i.get("status", "")), 12) + " "
        ss = sessions_text(i)
        tail = ("  " + c("cyan", ss)) if ss else ""
        return head + trim(i.get("subject", ""), max(w - dw(head) - dw(tail), 10)) + tail

    def full(w):
        return redmine_lines(i)

    claude = next((s["slot"] for s in i.get("sessions") or [] if s.get("kind") == "claude"), None)
    return {"key": str(i["id"]), "group": group, "row": row, "full": full, "url": i.get("url", ""),
            "enter": lambda: TextView(lambda: (f"#{i['id']}", ["  " + ln for ln in redmine_lines(i, detail=True)]
                                               + ((["", "  " + hp.rule(cols_rows()[0] - 4, f"[{claude}] の枠")] + hp.render_slot(claude, 60).split("\n")[2:])
                                                  if claude else []), i.get("url", "")))}


def redmine_lines(i, detail=False):
    out = [c("gray", "件名 ") + i.get("subject", "")]
    if detail:
        out.append(c("gray", "優先度 ") + (i.get("priority") or "?") + c("gray", "  ステータス ") + i.get("status", "")
                   + (c("gray", "  担当 ") + i["assignee"] if i.get("assignee") else "") + ("  [ウォッチ]" if i.get("watch") else ""))
    waits = [r for r in i.get("relations") or [] if r.get("kind") == "wait" and not r.get("closed")]
    blocks = [r for r in i.get("relations") or [] if r.get("kind") == "blocking" and not r.get("closed")]
    if waits:
        out.append(c("yellow", "待ち ") + " ".join(f"#{r['id']}({r.get('status') or r.get('phrase') or '?'}) {r.get('subject', '')}" for r in waits))
    if blocks:
        out.append(c("gray", "ブロック先 ") + " ".join(f"#{r['id']}" for r in blocks))
    ss = sessions_text(i)
    if ss:
        out.append(c("gray", "作業中の枠 ") + c("cyan", ss))
    last = i.get("last") or {}
    if last.get("on"):
        import hub_redmine as hr
        out.append(c("gray", "最終更新 ") + ("自分" if last.get("me") else "他") + " " + hr.jst(last["on"]))
        if last.get("note"):
            out.append(c("gray", "最新コメント ") + ("（自分）" if last.get("note_me") else "") + re.sub(r"\s+", " ", last["note"]))
    if detail and i.get("url"):
        out.append(c("gray", "URL ") + c("blue", i["url"]))
    return out


# ---- 本体 -----------------------------------------------------------------------------------------

def main():
    a = sys.argv[1:]
    kind = a[0] if a else "list"
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    out = sys.stdout
    try:
        tty.setraw(fd)
        out.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[H\x1b[2J  読み込み中…")
        out.flush()
        if kind == "slot":
            stack = [slot_view(int(a[1]), int(a[2]) if len(a) > 2 else 80)]
        elif kind == "watch":
            if any(x in ("refresh", "--refresh", "再取得") for x in a[1:]):
                import hub_watch as hw
                hw.fetch(True)  # その場で判定し直す
            stack = [watch_view()]
        elif kind == "redmine":
            stack = [redmine_view(a[1:])]
        elif kind == "order":
            stack = [order_view()]
        else:
            stack = [list_view()]
        while stack:
            cols, rows = cols_rows()
            v = stack[-1]
            if v.auto and time.time() - getattr(v, "loaded", 0) > AUTO_RELOAD:
                v.reload()
            lines, foot = v.draw(cols, rows)
            buf = ["\x1b[H"]
            for k in range(rows - 1):
                buf.append("\x1b[2K" + (pg.cut(lines[k], 0, cols) if k < len(lines) else "") + "\r\n")
            buf.append("\x1b[2K\x1b[2m" + trim(foot, cols - 1) + "\x1b[0m")
            out.write("".join(buf))
            out.flush()
            import select
            if not select.select([fd], [], [], AUTO_RELOAD if v.auto else None)[0]:
                continue
            for k in pg.read_keys(fd):
                if k == "\x03":
                    stack = []
                    break
                r = stack[-1].key(k, cols, rows)
                if r == "back":
                    stack.pop()
                    if not stack:
                        break
                elif r is not None:
                    out.write("\x1b[H\x1b[2J  読み込み中…")
                    out.flush()
                    stack.append(r)
    finally:
        out.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[?1049l")
        out.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
