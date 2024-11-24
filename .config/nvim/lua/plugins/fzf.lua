-- GGrepコマンドを定義 (git grep を fzf で実行)
vim.api.nvim_create_user_command('GGrep', function(opts)
  local command = 'git grep --line-number ' .. vim.fn.shellescape(opts.args)
  local git_root = vim.fn.systemlist('git rev-parse --show-toplevel')[1]
  vim.fn['fzf#vim#grep'](command, 0, vim.fn['fzf#vim#with_preview']({ dir = git_root }), opts.bang and 0 or nil)
end, { bang = true, nargs = '*' })

-- fzfの検索コマンドに対するキーマッピング
vim.api.nvim_set_keymap('n', ',f', ':Files<CR>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',g', ':GFiles<CR>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',G', ':GFiles?<CR>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',r', ':Rg<CR>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',b', ':Buffers<CR>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',l', ':BLines<CR>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',h', ':History<CR>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',m', ':Mark<CR>', { noremap = true, silent = true })

