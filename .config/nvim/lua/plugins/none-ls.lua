local null_ls = require("null-ls")

null_ls.setup({
  sources = {
    null_ls.builtins.formatting.prettier,
    require("none-ls.diagnostics.eslint"),
    require("none-ls.code_actions.eslint"),
    null_ls.builtins.diagnostics.rubocop.with({
      command = "rubocop",
      args = {"--disable-plugins"},
    }),
    null_ls.builtins.formatting.rubocop.with({
      command = "rubocop",
      args = {"--disable-plugins"},
    })
  }
})
