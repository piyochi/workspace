#!/bin/bash

# コピー元とコピー先を指定
SOURCE_NVIM_INIT="$HOME/workspace/.config/nvim/init.lua"
SOURCE_NVIM_LUA="$HOME/workspace/.config/nvim/lua/"
SOURCE_MCPHUB="$HOME/workspace/.config/mcphub/"
SOURCE_BIN="$HOME/workspace/bin/claude-monitor"
SOURCE_TMUXP="$HOME/workspace/.tmuxp/ticket_v2_project"
SOURCE_TMUXP_YAML="$HOME/workspace/.tmuxp/ticket_v2_project.yaml"
DEST_NVIM="$HOME/.config/nvim/"
DEST_NVIM_LUA="$HOME/.config/nvim/lua/"
DEST_MCPHUB="$HOME/.config/mcphub/"
DEST_BIN="$HOME/bin/"
DEST_TMUXP="$HOME/.tmuxp/ticket_v2_project/"
DEST_TMUXP_YAML="$HOME/.tmuxp/"
SOURCE_DASHBOARD="$HOME/workspace/.local/share/dev-dashboard"
DEST_DASHBOARD="$HOME/.local/share/dev-dashboard/"

# 確認プロンプトを表示
read -p "設定ファイル (nvim, mcphub, bin, tmuxp, dev-dashboard, hub) を home にコピーしますか？ [Y/n]: " CONFIRM

# 入力を大文字に変換して確認
CONFIRM=${CONFIRM^^} # 小文字を大文字に変換
if [[ "$CONFIRM" != "Y" && "$CONFIRM" != "" ]]; then
  echo "キャンセルしました。"
  exit 0
fi

# nvim init.lua をコピー
echo "Copying $SOURCE_NVIM_INIT to $DEST_NVIM..."
mkdir -p "$DEST_NVIM" # コピー先ディレクトリ作成
cp "$SOURCE_NVIM_INIT" "$DEST_NVIM"

# nvim lua/ をコピー（.DS_Storeを除外）
echo "Copying $SOURCE_NVIM_LUA to $DEST_NVIM_LUA..."
mkdir -p "$DEST_NVIM_LUA" # luaディレクトリを作成
rsync -av --exclude='.DS_Store' "$SOURCE_NVIM_LUA" "$DEST_NVIM_LUA"

# mcphub/ をコピー（.DS_Storeを除外）
if [ -d "$SOURCE_MCPHUB" ]; then
  echo "Copying $SOURCE_MCPHUB to $DEST_MCPHUB..."
  mkdir -p "$DEST_MCPHUB" # mcphubディレクトリを作成
  rsync -av --exclude='.DS_Store' "$SOURCE_MCPHUB" "$DEST_MCPHUB"
else
  echo "Warning: $SOURCE_MCPHUB が見つかりません。スキップします。"
fi

# claude-monitor を ~/bin/ にコピー
if [ -f "$SOURCE_BIN" ]; then
  echo "Copying $SOURCE_BIN to $DEST_BIN..."
  mkdir -p "$DEST_BIN"
  cp "$SOURCE_BIN" "${DEST_BIN}claude-monitor"
  chmod +x "${DEST_BIN}claude-monitor"
else
  echo "Warning: $SOURCE_BIN が見つかりません。スキップします。"
fi

# tmuxp ticket_v2_project をコピー
if [ -d "$SOURCE_TMUXP" ]; then
  echo "Copying $SOURCE_TMUXP to $DEST_TMUXP..."
  mkdir -p "$DEST_TMUXP"
  rsync -av --exclude='.DS_Store' "$SOURCE_TMUXP/" "$DEST_TMUXP"
fi
if [ -f "$SOURCE_TMUXP_YAML" ]; then
  echo "Copying $SOURCE_TMUXP_YAML to $DEST_TMUXP_YAML..."
  cp "$SOURCE_TMUXP_YAML" "$DEST_TMUXP_YAML"
fi

# dev-dashboard をコピー（合言葉入りの config.json・cache・ログは home 側のものを残す）
if [ -d "$SOURCE_DASHBOARD" ]; then
  echo "Copying $SOURCE_DASHBOARD to $DEST_DASHBOARD..."
  mkdir -p "$DEST_DASHBOARD"
  rsync -av --exclude='.DS_Store' --exclude='config.json' --exclude='cache/' --exclude='backup/' \
    --exclude='server.log' --exclude='__pycache__/' --exclude='README.md' --exclude='.gitignore' \
    "$SOURCE_DASHBOARD/" "$DEST_DASHBOARD"
  echo "  server.py を変えたときは launchctl kickstart -k gui/\$(id -u)/local.dev-dashboard で反映"
fi

# hub（~/www/ticket_v2_hub の取りまとめ用。README・hub_status.py・na_to.py・hub_redmine.py・/na-to・/na-list・/na-redmine・/na-order のスキル本体）をコピー
SOURCE_HUB="$HOME/workspace/.local/share/ticket-v2/hub"
DEST_HUB="$HOME/.local/share/ticket-v2/hub/"
HUB_WS="$HOME/www/ticket_v2_hub"
if [ -d "$SOURCE_HUB" ]; then
  echo "Copying $SOURCE_HUB to $DEST_HUB..."
  mkdir -p "$DEST_HUB"
  rsync -av --exclude='.DS_Store' --exclude='__pycache__/' --exclude='order.json*' "$SOURCE_HUB/" "$DEST_HUB"  # order.json は /na-order の固定の順（個人の作業状態）
  # hub の workspace があれば、スキルへのシンボリックリンクと git の除外を作る（「/」の候補に /na-to・/na-list・/na-redmine・/na-order を出すため）
  if [ -d "$HUB_WS/.claude/skills" ]; then
    for s in na-to na-list na-redmine na-order; do
      ln -sfn "$HOME/.local/share/ticket-v2/hub/skills/$s" "$HUB_WS/.claude/skills/$s"
      grep -qxF "/.claude/skills/$s" "$HUB_WS/.git/info/exclude" 2>/dev/null || echo "/.claude/skills/$s" >> "$HUB_WS/.git/info/exclude"
    done
    echo "  hook（$HUB_WS/.claude/settings.local.json の UserPromptSubmit に na_to.py --hook）は手で設定する（README の /na-to の項目）"
  else
    echo "  $HUB_WS が無いのでスキルのリンクは作りません（hub を clone した後にもう一度実行）"
  fi
fi

if [ $? -eq 0 ]; then
  echo "指定されたファイルとディレクトリをホームに正常にコピーしました。"
else
  echo "エラー: コピーに失敗しました。"
fi
