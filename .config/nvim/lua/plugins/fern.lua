-- Fern の設定
vim.g['fern#default_hidden'] = 1
vim.api.nvim_set_keymap('n', '<C-e>', ':Fern . -reveal=% -drawer -toggle -width=40<CR>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<C-u>', ':Fern . -reveal=%<CR>', { noremap = true, silent = true })

