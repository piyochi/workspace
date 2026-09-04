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
      -- null-ls は format="json" のソースで stderr が空でないと即エラーにする
      -- (generator_factory.lua の `error("error in generator output: "..)`)。
      -- rubocop は非推奨通知を stderr に出すことがあり、それだけで診断が丸ごと死ぬ。
      --   例: rubocop 1.75 の「plugins: rubocop-rails を使え」通知
      -- 本物の失敗は check_exit_code (code>=2 で異常) 側で捕捉できるので無視して良い。
      ignore_stderr = true,
      -- Ruby自体の warning も抑止する(将来また警告が増えた時の保険)
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

