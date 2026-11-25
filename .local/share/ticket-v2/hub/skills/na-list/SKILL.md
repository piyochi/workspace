---
name: na-list
description: hub の monitor タブの12枠（環境1〜4の Claude / Codex）の状態を1枠2行で画面に出す。表示は hub の UserPromptSubmit hook が行う
argument-hint: "[枠 [行数]]（枠を指定するとその枠だけ詳しく。例: 7・7 60）"
disable-model-invocation: true
---

# na-list（hub 専用）

このスキルは「/」の候補に `/na-list` を出すためだけにある。表示は hub の `.claude/settings.local.json` の
UserPromptSubmit hook（`~/.local/share/ticket-v2/hub/bin/na_to.py --hook`）が行い、プロンプトを止めるので、
通常はこの本文が読まれることはない。

この本文が読まれた＝hook が動いていない。`python3 ~/.local/share/ticket-v2/hub/bin/hub_status.py --compact` を実行し（枠の指定があれば `python3 -c` で `hub_status.detail_text(枠, 行数)` を出し）、
出力をそのまま返して終える。
