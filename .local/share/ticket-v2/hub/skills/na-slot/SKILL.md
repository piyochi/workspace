---
name: na-slot
description: 自動で割り当てる Claude の枠から外す・戻す（例 /na-slot off 11 12）。処理は hub の UserPromptSubmit hook が行う
argument-hint: "[off|on 枠…]（引数なしで表示）"
disable-model-invocation: true
---

# na-slot（hub 専用）

このスキルは「/」の候補に `/na-slot` を出すためだけにある。処理は hub の `.claude/settings.local.json` の
UserPromptSubmit hook（`~/.local/share/ticket-v2/hub/bin/na_to.py --hook`）が行い、プロンプトを止めるので、
通常はこの本文が読まれることはない。除外した枠は `~/.local/share/ticket-v2/hub/slots.json` に保存する。

この本文が読まれた＝hook が動いていない。`python3 ~/.local/share/ticket-v2/hub/bin/hub_watch.py --slot $ARGUMENTS` を実行し、
出力をそのまま返して終える。
