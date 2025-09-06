local M = {}

-- Neovim 0.10+ では get_clients 推奨。無ければ get_active_clients を使う
local function get_clients(opts)
  if vim.lsp.get_clients then
    return vim.lsp.get_clients(opts or { bufnr = 0 })
  else
    return vim.lsp.get_active_clients(opts or { bufnr = 0 })
  end
end

local function has(client_name)
  for _, c in ipairs(get_clients({ bufnr = 0 })) do
    if c.name == client_name then return true end
  end
  return false
end

function M.smart_format()
  -- React 系は素の言語に正規化
  local ft_alias = {
    javascriptreact = "javascript",
    typescriptreact = "typescript",
  }
  local ft = ft_alias[vim.bo.filetype] or vim.bo.filetype

  -- 言語別の優先クライアント
  local preferred = {
    ruby = function()
      return { filter = function(c) return c.name == "null-ls" end }
    end,

    javascript = function()
      if has("eslint") then
        return { filter = function(c) return c.name == "eslint" end }
      else
        return { filter = function(c) return c.name == "null-ls" end }
      end
    end,

    typescript = function()
      if has("eslint") then
        return { filter = function(c) return c.name == "eslint" end }
      else
        return { filter = function(c) return c.name == "null-ls" end }
      end
    end,
  }

  local opts = { timeout_ms = 20000 }
  if preferred[ft] then
    local p = preferred[ft]()
    if p then opts.filter = p.filter end
  end

  -- 実際にフォーマット可能なクライアントが居るか確認
  local ok = false
  for _, c in ipairs(get_clients({ bufnr = 0 })) do
    if (not opts.filter or opts.filter(c))
      and c.server_capabilities
      and (c.server_capabilities.documentFormattingProvider
        or c.server_capabilities.documentRangeFormattingProvider) then
      ok = true
      break
    end
  end

  if ok then
    vim.lsp.buf.format(opts)
  else
    vim.notify("No formatter available for " .. (ft or "?"), vim.log.levels.WARN)
  end
end

return M
