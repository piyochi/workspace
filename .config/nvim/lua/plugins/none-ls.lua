local null_ls = require("null-ls")

null_ls.setup({
  sources = {
    -- Prettier をフォーマッターとして使用
    null_ls.builtins.formatting.prettier,

    -- ESLint の診断とコードアクション
    require("none-ls.diagnostics.eslint"),
    require("none-ls.code_actions.eslint"),

    -- RuboCop の診断設定
    null_ls.builtins.diagnostics.rubocop.with({
      command = "rubocop",
      args = {
        "--disable-pending-cops", -- 修正済みオプション
        "--format", "json",       -- null-ls 用に JSON 形式で出力
        "--force-exclusion",      -- 除外設定を強制
      },
    }),

    -- RuboCop のフォーマッター設定
    null_ls.builtins.formatting.rubocop.with({
      command = "rubocop",
      args = { "--stdin", "$FILENAME", "--auto-correct", "--stderr" }, -- stdin 方式
      -- prefer_local = "bin", -- bundler 環境なら推奨
    }),
    -- null_ls.builtins.formatting.rubocop.with({
    --   command = "rubocop",
    --   args = {
    --     "--disable-pending-cops", -- 修正済みオプション
    --     "--auto-correct",         -- 自動修正
    --     "--format", "files",
    --     "$FILENAME"
    --   },
    -- }),
  },
})

