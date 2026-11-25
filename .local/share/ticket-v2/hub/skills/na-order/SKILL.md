---
name: na-order
description: /na-redmine の先頭に固定するチケットの順（緊急の割り込みなど）を hub だけで持つ。表示・変更は hub の UserPromptSubmit hook が行う
argument-hint: "[番号 番号…（この順で置き換え）|番号 順位|+番号|-番号|clear]（引数なしで表示）"
disable-model-invocation: true
---

# na-order（hub 専用）

このスキルは「/」の候補に `/na-order` を出すためだけにある。処理は hub の `.claude/settings.local.json` の
UserPromptSubmit hook（`~/.local/share/ticket-v2/hub/bin/na_to.py --hook`）が行い、プロンプトを止めるので、
通常はこの本文が読まれることはない。順は `~/.local/share/ticket-v2/hub/order.json` に保存する。

この本文が読まれた＝hook が動いていない。`python3 ~/.local/share/ticket-v2/hub/bin/hub_redmine.py --order $ARGUMENTS` を実行し、
出力をそのまま返して終える。
