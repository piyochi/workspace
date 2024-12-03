-- vim.optは後から設定された値が優先される
-- vim.oは最後に設定された値が優先される

-- オプションの設定
vim.opt.ai = true
vim.opt.sw = 2
vim.opt.list = true
vim.opt.nu = true
vim.opt.showmode = true
vim.opt.expandtab = true
vim.opt.ts = 2
vim.o.encoding = 'utf-8'
vim.o.fileencoding = 'utf-8'
--vim.o.fileencodings = {'utf-8', 'iso-2022-jp', 'sjis', 'euc-jp'}
vim.o.fileencodings = 'utf-8,iso-2022-jp,sjis,euc-jp'
vim.opt.backspace = {'indent', 'eol', 'start'}
vim.opt.autoindent = true
vim.opt.ambiwidth = 'double'
-- マウスの右クリックを無効に
vim.opt.mouse = ''
-- デフォルトで検索時の背景色をOFFにする
vim.o.hlsearch = false
-- ステータスラインを常に表示
vim.o.laststatus = 2
-- 上部のタブラインをタブが1つ以上あるときに表示
vim.o.showtabline = 2
-- 24ビットカラーを使用
vim.o.termguicolors = true
-- カラースキームを設定
vim.cmd("colorscheme koehler")
-- モード表示をオフにする
vim.o.showmode = false
-- Python3 設定
vim.g.python3_host_prog = vim.fn.system("(type pyenv &>/dev/null && pyenv which python) || which python3")

-- ステータスラインの色設定
vim.cmd [[
  set statusline=%<%f\ %m%r%h%w%{'['.(&fenc!=''?&fenc:&enc).']['.&ff.']'}%=%l,%c%V%8P%{fugitive#statusline()}
  highlight statusline guifg=#FFFFFF guibg=#3399AA
  highlight statuslinenc guifg=#000000 guibg=#CCCCCC
]]

-- ターミナルモードで <Esc> をノーマルモードに切り替え
vim.api.nvim_set_keymap('t', '<Esc>', [[<C-\><C-n>]], { noremap = true, silent = true })
-- ターミナルを開いたら自動でインサートモード
vim.api.nvim_create_autocmd("TermOpen", {
  pattern = "*",
  command = "startinsert",
})
-- :T コマンドで画面下にターミナルを開く
vim.api.nvim_create_user_command("T", function(opts)
  vim.cmd("split")
  vim.cmd("wincmd j")
  vim.cmd("resize 20")
  vim.cmd("terminal " .. (opts.args or ""))
end, { nargs = "*" })

-- インデントガイドの色設定
vim.g.indentLine_color_gui = "#999999"

-- 上部タブ名にファイル名のみを表示
require('plugins.custom-tabline')
vim.o.tabline = "%!v:lua.require'plugins.custom-tabline'.my_tabline()"

-- neovim/nvim-lspconfigのソースコードチェックで以下の警告を無視する
-- 基本的にソースコードのチェックはnone-lsを使うためlspconfigでしか出ない警告は無視する
--   'json' is deprecated.
vim.lsp.handlers["textDocument/publishDiagnostics"] = function(_, result, ctx, config)
  if not result.diagnostics then return end

  -- 'json' is deprecated. のメッセージを除外
  result.diagnostics = vim.tbl_filter(function(diagnostic)
    return diagnostic.message ~= "'json' is deprecated."
  end, result.diagnostics)

  vim.lsp.diagnostic.on_publish_diagnostics(_, result, ctx, config)
end

