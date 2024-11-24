require('core.plugins')
vim.api.nvim_create_autocmd("BufWritePost", {
  pattern = { "plugins.lua" },
  command = "PackerCompile",
})
require('utils.functions')
require('core.settings')

require('plugins.fern')
require('plugins.ddc')
require('plugins.taglist')
require('plugins.fzf')
require('plugins.telescope')
require('plugins.vim-gitgutter')
require('plugins.github-copilot')
require('plugins.nvim-dap')

require('core.keymaps')

-- ~/.vimrc を読み込む
-- vim.cmd([[
--   source ~/.vimrc
-- ]])
--
-- vim.cmd([[
--   set runtimepath^=~/.vim
--   set runtimepath+=~/.vim/after
--   let &packpath = &runtimepath
-- ]])
