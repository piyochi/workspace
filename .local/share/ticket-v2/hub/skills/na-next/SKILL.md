---
name: na-next
description: 固定したチケットを止まっている所から次のスキルへ進め、以後は自動で頼む対象にする（ct-analyze・ct-architect・ct-planner の後で止まる）。処理は hub の UserPromptSubmit hook が行う
argument-hint: "番号 [枠] [sweep] [scope] [model=…] [effort=…] [dry]"
disable-model-invocation: true
---

# na-next（hub 専用）

このスキルは「/」の候補に `/na-next` を出すためだけにある。処理は hub の `.claude/settings.local.json` の
UserPromptSubmit hook（`~/.local/share/ticket-v2/hub/bin/na_to.py --hook`）が行い、プロンプトを止めるので、
通常はこの本文が読まれることはない。判定と送信は開発ダッシュボード（`POST /api/watch/next`）が行う。

この本文が読まれた＝hook が動いていない。`python3 ~/.local/share/ticket-v2/hub/bin/hub_watch.py --next $ARGUMENTS` を実行し、
出力をそのまま返して終える。
