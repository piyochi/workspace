-- nvimが起動したらcopilotを無効にする
vim.api.nvim_create_autocmd("VimEnter", {
  pattern = "*",
  callback = function()
    vim.api.nvim_command("Copilot disable")
  end,
})

-- \cpでCopilotの有効無効を切り替える
local copilot_enabled = false
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

