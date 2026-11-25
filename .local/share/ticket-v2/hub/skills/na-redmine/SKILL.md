---
name: na-redmine
description: 優先度で絞り込める。自分担当の未完了チケットとウォッチ中のチケットを、作業中の枠・待ち・最終更新付きで1件2行で画面に出す。表示は hub の UserPromptSubmit hook が行う
argument-hint: "[件数] [now|urgent|high|normal|low|high+|all（既定は上から2段。日本語も可）] [refresh]"
disable-model-invocation: true
---

# na-redmine（hub 専用）

このスキルは「/」の候補に `/na-redmine` を出すためだけにある。表示は hub の `.claude/settings.local.json` の
UserPromptSubmit hook（`~/.local/share/ticket-v2/hub/bin/na_to.py --hook`）が行い、プロンプトを止めるので、
通常はこの本文が読まれることはない。データは開発ダッシュボードの `/api/redmine`（5分キャッシュ）から読む。

この本文が読まれた＝hook が動いていない。`python3 ~/.local/share/ticket-v2/hub/bin/hub_redmine.py $ARGUMENTS` を実行し、
出力をそのまま返して終える。
