-- -- typescriptでブレークポイント使うやつだがまだ動いてない後日調整予定
-- -- Plug 'mfussenegger/nvim-dap'
-- -- Plug 'mxsdev/nvim-dap-vscode-js'
-- -- nvim-dap の設定
-- local dap = require("dap")
--
-- -- nvim-dap-vscode-js のセットアップ
-- require("dap-vscode-js").setup({
--   node_path = "node", -- Node.js のパス
--   --debugger_path = vim.fn.stdpath("data") .. "/mason/packages/js-debug-adapter", -- debugger のパス
--   debugger_path = "/Users/piyoh/vscode-js-debug",
--   adapters = { "pwa-node", "pwa-chrome", "pwa-firefox", "node-terminal", "pwa-extensionHost" },
-- })
--
-- -- JavaScript/TypeScript の DAP 設定
-- dap.configurations.javascript = {
--   {
--     type = "pwa-node",
--     request = "launch",
--     name = "Launch file",
--     program = "${file}",
--     cwd = "${workspaceFolder}",
--   },
--   {
--     type = "pwa-node",
--     request = "attach",
--     name = "Attach",
--     processId = require'dap.utils'.pick_process,
--     cwd = "${workspaceFolder}",
--   }
-- }
-- dap.configurations.typescript = dap.configurations.javascript
--