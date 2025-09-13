## Redmine MCP

### .bashrc or .zshrc にENV追加

APIキーはRedmineにログインして「/my/account」にアクセスして確認

```
export REDMINE_HOST=https://redmine.corich.info
export REDMINE_API_KEY=xxxxxxxxxxx
```

### Node版 MCPサーバーをインストール

```
git clone https://github.com/yonaka15/mcp-server-redmine
cd mcp-server-redmine
npm install
npm run build
# 開発起動
npm run dev
# もしくは node で dist/index.js を起動
```

### mcp.jsonに設定を追加

```
"redmine": {
  "command": "node",
  # サーバーを起動してるファイルを指定する
  "args": ["/Users/piyoh/mcp/mcp-server-redmine/dist/index.js"],
  "env": {
    "REDMINE_HOST": "${env:REDMINE_HOST}",
    "REDMINE_API_KEY": "${env:REDMINE_API_KEY}"
  }
}
```

