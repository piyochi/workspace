#!/bin/bash

# コピー元とコピー先を指定
SOURCE_INIT="$HOME/.config/nvim/init.lua"
SOURCE_LUA="$HOME/.config/nvim/lua/"
DEST="$HOME/workspace/.config/nvim/"
DEST_LUA="$HOME/workspace/.config/nvim/lua/"

# 確認プロンプトを表示
read -p "設定ファイル ($SOURCE_INIT と $SOURCE_LUA) を $DEST にコピーしますか？ [Y/n]: " CONFIRM

# 入力を大文字に変換して確認
CONFIRM=${CONFIRM^^} # 小文字を大文字に変換
if [[ "$CONFIRM" != "Y" && "$CONFIRM" != "" ]]; then
  echo "キャンセルしました。"
  exit 0
fi

# init.lua をコピー
echo "Copying $SOURCE_INIT to $DEST..."
mkdir -p "$DEST" # コピー先ディレクトリ作成
cp "$SOURCE_INIT" "$DEST"

# lua/ をコピー
echo "Copying $SOURCE_LUA to $DEST_LUA..."
mkdir -p "$DEST_LUA" # luaディレクトリを作成
cp -r "$SOURCE_LUA" "$DEST_LUA"

if [ $? -eq 0 ]; then
  echo "指定されたファイルとディレクトリをワークスペースに正常にコピーしました。"
else
  echo "エラー: コピーに失敗しました。"
fi

