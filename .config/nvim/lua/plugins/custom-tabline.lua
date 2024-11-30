-- 上部タブ名にファイル名のみを表示
local M = {}

function M.my_tabline()
  local s = ""

  for i = 1, vim.fn.tabpagenr('$') do
    local bufnrs = vim.fn.tabpagebuflist(i)
    local win_nr = vim.fn.tabpagewinnr(i)
    local bufnr = bufnrs[win_nr]

    -- バッファ番号が有効か確認
    if bufnr and vim.fn.bufexists(bufnr) == 1 then
      local file_name = vim.fn.fnamemodify(vim.fn.bufname(bufnr), ":t")

      -- ファイル名が空の場合は [ ] を表示
      if file_name == "" then
        file_name = "[ ]"
      end

      local highlight = (i == vim.fn.tabpagenr()) and "%#TabLineSel#" or "%#TabLine#"
      s = s .. "%" .. i .. "T" .. highlight .. file_name .. " "
    else
      -- 無効なバッファの場合は [No Name] を表示
      local highlight = (i == vim.fn.tabpagenr()) and "%#TabLineSel#" or "%#TabLine#"
      s = s .. "%" .. i .. "T" .. highlight .. "[No Name] "
    end
  end

  s = s .. "%#TabLineFill#%T"
  return s
end

return M

