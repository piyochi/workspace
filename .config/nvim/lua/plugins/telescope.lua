-- Telescopeのキーマッピング
-- <leader> は \ にマッピングされている
-- vim.api.nvim_set_keymap('n', '<leader>ff', '<cmd>lua require("telescope.builtin").find_files()<cr>', { noremap = true, silent = true })
-- vim.api.nvim_set_keymap('n', '<leader>fg', '<cmd>lua require("telescope.builtin").git_files()<cr>', { noremap = true, silent = true })
-- vim.api.nvim_set_keymap('n', '<leader>fr', '<cmd>lua require("telescope.builtin").live_grep()<cr>', { noremap = true, silent = true })
-- vim.api.nvim_set_keymap('n', '<leader>fb', '<cmd>lua require("telescope.builtin").buffers()<cr>', { noremap = true, silent = true })
-- vim.api.nvim_set_keymap('n', '<leader>fh', '<cmd>lua require("telescope.builtin").oldfiles()<cr>', { noremap = true, silent = true })
-- vim.api.nvim_set_keymap('n', '<leader>fm', '<cmd>lua require("telescope.builtin").marks()<cr>', { noremap = true, silent = true })
-- vim.api.nvim_set_keymap('n', '<leader>ft', '<cmd>lua require("telescope.builtin").help_tags()<cr>', { noremap = true, silent = true })
-- vim.api.nvim_set_keymap('n', '<leader>fs', '<cmd>lua require("telescope.builtin").search_history()<cr>', { noremap = true, silent = true })
-- vim.api.nvim_set_keymap('n', '<leader>fc', '<cmd>lua require("telescope.builtin").command_history()<cr>', { noremap = true, silent = true })

vim.api.nvim_set_keymap('n', ',f', '<cmd>lua require("telescope.builtin").find_files()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',g', '<cmd>lua require("telescope.builtin").git_files()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',r', '<cmd>lua require("telescope.builtin").live_grep()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',b', '<cmd>lua require("telescope.builtin").buffers()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',h', '<cmd>lua require("telescope.builtin").oldfiles()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',m', '<cmd>lua require("telescope.builtin").marks()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',t', '<cmd>lua require("telescope.builtin").help_tags()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',s', '<cmd>lua require("telescope.builtin").search_history()<cr>', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', ',c', '<cmd>lua require("telescope.builtin").command_history()<cr>', { noremap = true, silent = true })

local actions = require("telescope.actions")
local action_state = require("telescope.actions.state")

-- カスタムアクション: 選択済みの項目をQuickfixリストに送る。未選択の場合はすべて送る。
local function send_to_qflist_or_all(prompt_bufnr)
  local picker = action_state.get_current_picker(prompt_bufnr)
  local selected_entries = picker:get_multi_selection()

  if #selected_entries == 0 then
    -- 未選択の場合は全件をQuickfixリストに送信
    actions.smart_send_to_qflist(prompt_bufnr)
  else
    -- 選択済みの項目をQuickfixリストに送信
    actions.send_selected_to_qflist(prompt_bufnr)
  end

  -- Quickfixリストを開く
  vim.cmd("copen")
end

require("telescope").setup({
  defaults = {
    mappings = {
      i = { -- Insertモードのマッピング
        ["<C-q>"] = send_to_qflist_or_all, -- カスタムアクションをCtrl+qに割り当て
      },
      n = { -- Normalモードのマッピング
        ["<C-q>"] = send_to_qflist_or_all, -- カスタムアクションをCtrl+qに割り当て
      },
    },
  },
})

