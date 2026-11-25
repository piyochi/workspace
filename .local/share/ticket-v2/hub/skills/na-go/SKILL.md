---
name: na-go
description: 設計（ct-issue-docs）まで済んだチケットの実装を始める（ct-ship-loop を頼み、終わったら ct-finish を自動で頼む）。処理は hub の UserPromptSubmit hook が行う
argument-hint: "番号 [枠] [--branch 名前（既定 feature/番号）] [force] [dry]"
disable-model-invocation: true
---

# na-go（hub 専用）

このスキルは「/」の候補に `/na-go` を出すためだけにある。処理は hub の `.claude/settings.local.json` の
UserPromptSubmit hook（`~/.local/share/ticket-v2/hub/bin/na_to.py --hook`）が行い、プロンプトを止めるので、
通常はこの本文が読まれることはない。判定と送信は開発ダッシュボード（`POST /api/watch/go`）が行う。

この本文が読まれた＝hook が動いていない。`python3 ~/.local/share/ticket-v2/hub/bin/hub_watch.py --go $ARGUMENTS` を実行し、
出力をそのまま返して終える。
