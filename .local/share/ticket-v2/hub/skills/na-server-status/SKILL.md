---
name: na-server-status
description: 開発用サーバー（Docker）の使用中・順番待ち・経過時間・譲るまでの残り・各環境のサーバー・直近の記録を出す。release 番号で使用中を外す。表示は hub の UserPromptSubmit hook が行う
argument-hint: "[release 番号（使用中・順番待ちから外す）]"
disable-model-invocation: true
---

# na-server-status（hub 専用）

このスキルは「/」の候補に `/na-server-status` を出すためだけにある。処理は hub の `.claude/settings.local.json` の
UserPromptSubmit hook（`~/.local/share/ticket-v2/hub/bin/na_to.py --hook`）が行い、プロンプトを止めるので、
通常はこの本文が読まれることはない。状態は `~/.local/share/ticket-v2/hub/docker.json`（`hub_docker.py` が読み書きする）。

この本文が読まれた＝hook が動いていない。`python3 -B ~/.local/share/ticket-v2/hub/bin/hub_docker.py status` を実行し
（引数が `release 番号` なら先に `hub_docker.py release 番号`）、出力をそのまま返して終える。
