local null_ls = require("null-ls")

null_ls.setup({
  sources = {
    -- Prettier をフォーマッターとして使用
    null_ls.builtins.formatting.prettier,

    -- ESLint の診断とコードアクション
    require("none-ls.diagnostics.eslint"),
    require("none-ls.code_actions.eslint"),

    -- RuboCop の診断設定
    -- `--stdin $FILENAME` を必ず渡す。これを落とすとrubocopがカレントディレクトリ全体
    -- (実測1873ファイル/1分53秒)をスキャンしてタイムアウトする
    null_ls.builtins.diagnostics.rubocop.with({
      command = "rubocop",
      args = {
        "--disable-pending-cops", -- 修正済みオプション
        "-f", "json",             -- null-ls 用に JSON 形式で出力
        "--force-exclusion",      -- 除外設定を強制
        "--stdin", "$FILENAME",
      },
      -- custom_rubocops/*.rb が廃止APIを継承しており、その非推奨警告がstderrに出る。
      -- null-ls は format="json" のときstderrが空でないと即エラーにするため警告を抑止する
      env = { RUBYOPT = "-W0" },
    }),

    -- RuboCop のフォーマッター設定
    -- `--server` はrubocopデーモンで起動を高速化、`-f quiet` はレポート出力を抑止
    null_ls.builtins.formatting.rubocop.with({
      command = "rubocop",
      args = { "-a", "--server", "-f", "quiet", "--stderr", "--stdin", "$FILENAME" },
      env = { RUBYOPT = "-W0" },
      -- prefer_local = "bin" は使えない: vendor/bundle のgemがDocker(Linux)向けのため
      -- ホストでは bundle exec が Bundler::GemNotFound になる
    }),
  },
})

