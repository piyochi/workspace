# dev-dashboard

自宅 LAN の Windows ブラウザから見る開発ダッシュボード。

- Claude / Codex の使用率（5時間枠・週）とリセット時刻
- 環境1・2（env1 / env2）の api / app / sqs の状態と、起動・停止・再起動（`~/bin/local-server` を呼ぶ）

## 置き場所

実体は `~/.local/share/dev-dashboard/`。この workspace はその控え（合言葉入りの `config.json` は入れない）。

## セットアップ（新しい Mac に入れるとき）

```bash
mkdir -p ~/.local/share/dev-dashboard
cp ~/workspace/.local/share/dev-dashboard/* ~/.local/share/dev-dashboard/
cp ~/.local/share/dev-dashboard/config.example.json ~/.local/share/dev-dashboard/config.json
chmod 600 ~/.local/share/dev-dashboard/config.json   # key に合言葉を入れる

# 常駐（ログイン時に自動起動）
ln -s ~/.local/share/dev-dashboard/local.dev-dashboard.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/local.dev-dashboard.plist

# Claude の使用率の書き出しを各環境（~/www/ticket_v2*）のステータスラインに挟む
python3 ~/.local/share/dev-dashboard/install-statusline.py
```

開くのは `http://<MacのIP>:8765/?key=<合言葉>`（初回だけ。以降は cookie で覚える）。

## 変えたとき

- `server.py` を直した → `launchctl kickstart -k gui/$(id -u)/local.dev-dashboard`
- `index.html` / `config.json` → ブラウザを読み込み直すだけ
- Codex のアカウントを足す → `config.json` の `codex_homes`
- ステータスラインの挟み込みを外す → `install-statusline.py --remove`

## ファイル

| ファイル | 役割 |
|---|---|
| server.py | Web サーバー（合言葉・allow_ips のチェック、状態取得、操作の実行） |
| index.html | 画面 |
| statusline.py | Claude Code の statusLine。rate_limits を cache/ に書き、`--then` で既存のステータスラインに渡す |
| install-statusline.py | 各環境の `.claude/settings.local.json` に statusLine を足す / 外す |
| local.dev-dashboard.plist | launchd の常駐設定 |
| config.example.json | config.json のひな形 |
