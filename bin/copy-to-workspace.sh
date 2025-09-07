#!/bin/bash

# コピー元とコピー先を指定
SOURCE_NVIM_INIT="$HOME/.config/nvim/init.lua"
SOURCE_NVIM_LUA="$HOME/.config/nvim/lua/"
SOURCE_MCPHUB="$HOME/.config/mcphub/"
DEST_NVIM="$HOME/workspace/.config/nvim/"
DEST_NVIM_LUA="$HOME/workspace/.config/nvim/lua/"
DEST_MCPHUB="$HOME/workspace/.config/mcphub/"

# 確認プロンプトを表示
read -p "設定ファイル (nvim, mcphub) を workspace にコピーしますか？ [Y/n]: " CONFIRM

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

if [ $? -eq 0 ]; then
  echo "指定されたファイルとディレクトリをワークスペースに正常にコピーしました。"
else
  echo "エラー: コピーに失敗しました。"
fi
