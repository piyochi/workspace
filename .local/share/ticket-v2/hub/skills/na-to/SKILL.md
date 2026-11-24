---
name: na-to
description: hub から monitor タブの Claude の枠（奇数枠）に指示を送る。送信は hub の UserPromptSubmit hook が行う
argument-hint: <枠番号> <指示>（例: 3 /ct-redmine 14926）
disable-model-invocation: true
---

# na-to（hub 専用）

このスキルは「/」の候補に `/na-to` を出すためだけにある。送信は hub の `.claude/settings.local.json` の
UserPromptSubmit hook（`~/.local/share/ticket-v2/hub/bin/na_to.py --hook`）が行い、プロンプトを止めるので、
通常はこの本文が読まれることはない。

この本文が読まれた＝hook が動いていない。**送信はせず**、次の1行だけを返して終える:

「na-to の hook が動いていないため送っていません。hub の .claude/settings.local.json の hooks と /hooks を確認してください」
