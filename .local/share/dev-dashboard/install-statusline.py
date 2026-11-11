#!/usr/bin/env python3
"""各環境の .claude/settings.local.json に statusLine を足し、既存のステータスラインの前に
使用率の書き出し（statusline.py）を挟む。

プロジェクトの .claude/settings.json の statusLine（.claude/hooks/status-line.sh）は git 管理なので触らない。
settings.local.json は project の settings.json より優先されるので、こちらで上書きする。
画面の表示は既存の status-line.sh のまま変わらない。

使い方: python3 ~/.local/share/dev-dashboard/install-statusline.py          … 追加
        python3 ~/.local/share/dev-dashboard/install-statusline.py --remove … 元に戻す
"""
import glob
import json
import os
import shutil
import sys

HOME = os.path.expanduser("~")
SCRIPT = os.path.join(HOME, ".local/share/dev-dashboard/statusline.py")
MARK = "dev-dashboard/statusline.py"


def main():
    remove = "--remove" in sys.argv
    for proj in sorted(glob.glob(os.path.join(HOME, "www", "ticket_v2*"))):
        shared = os.path.join(proj, ".claude", "settings.json")
        local = os.path.join(proj, ".claude", "settings.local.json")
        if not os.path.isfile(shared):
            continue
        try:
            base_cmd = (json.load(open(shared)).get("statusLine") or {}).get("command")
        except ValueError:
            print(f"⚠️  {shared} を読めませんでした。飛ばします")
            continue
        try:
            cfg = json.load(open(local)) if os.path.isfile(local) else {}
        except ValueError:
            print(f"⚠️  {local} を読めませんでした。飛ばします")
            continue
        current = (cfg.get("statusLine") or {}).get("command", "")

        if remove:
            if MARK not in current:
                print(f"－ {proj}: 入っていません")
                continue
            cfg.pop("statusLine")
        else:
            if MARK in current:
                print(f"－ {proj}: 入っています")
                continue
            if current:
                print(f"⚠️  {proj}: settings.local.json に別の statusLine があるので触りません")
                continue
            cmd = f"python3 {SCRIPT}" + (f" --then {base_cmd}" if base_cmd else "")
            cfg["statusLine"] = {"type": "command", "command": cmd}

        if os.path.isfile(local):
            # 控えは git 管理のフォルダに置かない（未追跡ファイルとして git status に出てしまうため）
            backup_dir = os.path.join(HOME, ".local/share/dev-dashboard/backup")
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(local, os.path.join(backup_dir, f"{os.path.basename(proj)}.settings.local.json"))
        with open(local, "w") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"✅ {proj}: {'外しました' if remove else '追加しました'}")


if __name__ == "__main__":
    main()
