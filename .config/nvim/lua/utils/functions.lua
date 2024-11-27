local M = {}

-- none-lsのエラー表示を切り替える
local diagnostics_shown = true
function M.toggle_diagnostics()
  if diagnostics_shown then
    vim.diagnostic.hide()
  else
    vim.diagnostic.show()
  end
  diagnostics_shown = not diagnostics_shown
end

return M
