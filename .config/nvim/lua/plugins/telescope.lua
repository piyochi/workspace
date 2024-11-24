-- Telescopeのキーマッピング
-- <leader> は \ にマッピングされている
vim.api.nvim_set_keymap('n', '<leader>ff', '<cmd>lua require("telescope.builtin").find_files()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<leader>fg', '<cmd>lua require("telescope.builtin").git_files()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<leader>fr', '<cmd>lua require("telescope.builtin").live_grep()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<leader>fb', '<cmd>lua require("telescope.builtin").buffers()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<leader>fh', '<cmd>lua require("telescope.builtin").oldfiles()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<leader>fm', '<cmd>lua require("telescope.builtin").marks()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<leader>ft', '<cmd>lua require("telescope.builtin").help_tags()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<leader>fs', '<cmd>lua require("telescope.builtin").search_history()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<leader>fc', '<cmd>lua require("telescope.builtin").command_history()<cr>', { noremap = true, silent = true })

