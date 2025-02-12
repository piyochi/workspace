-- nvimが起動したらcopilotを有効にする
vim.api.nvim_create_autocmd("VimEnter", {
  -- pattern = "*",
  callback = function()
    -- vim.api.nvim_command("Copilot disable")
    vim.cmd("Copilot enable")
  end,
})

-- \cpでCopilotの有効無効を切り替える
-- local copilot_enabled = false
local copilot_enabled = true
function ToggleCopilot()
  if copilot_enabled then
    vim.cmd("Copilot disable")
    print("Copilot disabled")
  else
    vim.cmd("Copilot enable")
    print("Copilot enabled")
  end
  copilot_enabled = not copilot_enabled
end
vim.api.nvim_set_keymap("n", "<leader>cp", ":lua ToggleCopilot()<CR>", { noremap = true, silent = true })

