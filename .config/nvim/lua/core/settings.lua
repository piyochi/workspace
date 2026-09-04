-- vim.optは後から設定された値が優先される
-- vim.oは最後に設定された値が優先される

-- オプションの設定
vim.opt.sw = 2
vim.opt.list = true
vim.opt.nu = true
vim.opt.expandtab = true
vim.opt.ts = 2
-- tags: 開いているファイルの上位ディレクトリを遡って探す(セミコロンが上方向探索の意味)
-- これが無いと cwd がリポジトリ直下からズレた瞬間にタグジャンプが機能しなくなる
vim.opt.tags = './tags;,tags;'

-- g]/<C-]> を常に ctags(tagsファイル)に固定する。
-- nvim 0.11 は LSP のサーバ初期化完了時に tagfunc を v:lua.vim.lsp.tagfunc へ差し替え、
-- LSPシンボル検索(フルパス表示・kind名がModule/Method等の長い単語)になってしまう。
-- on_attach で空に戻しても lsp.lua の is_empty_or_default() が「空なら上書き可」と
-- 判定するため何度でも奪われる。そこで v:null を返す自前関数で枠を占有する
-- (`:h tagfunc` — v:null を返すと標準のtag検索にフォールバックする)。
-- 定義ジャンプは gd(LSP) が担当する。
function _G.ctags_only_tagfunc()
  return vim.NIL
end
vim.opt.tagfunc = 'v:lua._G.ctags_only_tagfunc'
vim.o.encoding = 'utf-8'
vim.o.fileencoding = 'utf-8'
--vim.o.fileencodings = {'utf-8', 'iso-2022-jp', 'sjis', 'euc-jp'}
vim.o.fileencodings = 'utf-8,iso-2022-jp,sjis,euc-jp'
vim.opt.backspace = {'indent', 'eol', 'start'}
vim.opt.autoindent = true
vim.opt.ambiwidth = 'single'
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
-- モード表示をオフにする(statuslineで代替表示するため)
vim.o.showmode = false

-- Python3 プロバイダは使わない(Python依存プラグインが無いため)。
-- 以前は pyenv を毎起動シェル実行して python3_host_prog に入れていたが、
-- 起動時間の約7割(330ms)を消費し、かつ vim.fn.system の戻り値に改行が付くため
-- executable() が 0 になりプロバイダ自体が機能していなかった。
vim.g.loaded_python3_provider = 0

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

-- 上部タブ名にファイル名のみを表示
require('plugins.custom-tabline')
vim.o.tabline = "%!v:lua.require'plugins.custom-tabline'.my_tabline()"

-- neovim/nvim-lspconfigのソースコードチェックで以下の警告を無視する
-- 基本的にソースコードのチェックはnone-lsを使うためlspconfigでしか出ない警告は無視する
vim.lsp.handlers["textDocument/publishDiagnostics"] = function(_, result, ctx, config)
  if not result.diagnostics then return end

  -- 除外するメッセージを配列として定義
  local exclude_messages = {
    "'json' is deprecated.",
    "Cannot find name 'JsonifyObject'.",
    " implicitly has an 'any' type.", -- Parameter 'e' implicitly has an 'any' type.
    " does not exist on type ", -- Property 'users' does not exist on type '{}'.
    " is not assignable to parameter of type 'ActionFunctionArgs'.",
    "Object literal may only specify known properties, and ",
  }

  -- メッセージが除外リストに含まれているかをチェック
  result.diagnostics = vim.tbl_filter(function(diagnostic)
    for _, msg in ipairs(exclude_messages) do
      -- if diagnostic.message == msg then 完全一致ならこっち
      if string.find(diagnostic.message, msg, 1, true) then
        return false -- 除外リストに含まれている場合は除外
      end
    end
    return true -- 含まれていなければ診断を保持
  end, result.diagnostics)

  vim.lsp.diagnostic.on_publish_diagnostics(_, result, ctx, config)
end

