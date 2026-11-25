---
name: na-watch
description: /na-order で固定したチケットの枠・スキル単位の段階・状態（処理中・確認待ち）を画面に出す。表示は hub の UserPromptSubmit hook が行う
argument-hint: "[refresh（その場で判定し直す）]"
disable-model-invocation: true
---

# na-watch（hub 専用）

このスキルは「/」の候補に `/na-watch` を出すためだけにある。処理は hub の `.claude/settings.local.json` の
UserPromptSubmit hook（`~/.local/share/ticket-v2/hub/bin/na_to.py --hook`）が行い、プロンプトを止めるので、
通常はこの本文が読まれることはない。判定は開発ダッシュボードの常駐ループ（20 秒ごと）が行う。

この本文が読まれた＝hook が動いていない。`python3 ~/.local/share/ticket-v2/hub/bin/hub_watch.py $ARGUMENTS` を実行し、
出力をそのまま返して終える。
