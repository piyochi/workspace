-- Gitの差分を表示するプラグイン
vim.g.gitgutter_highlight_lines = 0
vim.opt.updatetime = 250

-- キーマッピング
vim.api.nvim_set_keymap('n', ']h', '<Plug>GitGutterNextHunk', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '[h', '<Plug>GitGutterPrevHunk', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<Leader>hj', '<Plug>GitGutterStageHunk', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<Leader>hk', '<Plug>GitGutterRevertHunk', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<Leader>hv', '<Plug>GitGutterPreviewHunk', { noremap = true, silent = true })

