-- packer.nvimを自動インストール
local ensure_packer = function()
  local fn = vim.fn
  local install_path = fn.stdpath('data')..'/site/pack/packer/start/packer.nvim'
  if fn.empty(fn.glob(install_path)) > 0 then
    fn.system({'git', 'clone', '--depth', '1', 'https://github.com/wbthomason/packer.nvim', install_path})
    vim.cmd [[packadd packer.nvim]]
    return true
  end
  return false
end
local packer_bootstrap = ensure_packer()

-- packerの初期設定
return require('packer').startup(function(use)
  use 'wbthomason/packer.nvim' -- Packer自身を管理
  use 'nvim-lua/plenary.nvim'  -- 必須の依存プラグイン

  -- 検索結果を操作するためのプラグイン
  use 'vim-scripts/grep.vim'

  -- Rails アプリ開発をサポート
  use 'tpope/vim-rails'

  -- ファイルツリー表示と操作
  use 'lambdalisue/fern.vim'
  use 'LumaKernel/fern-mapping-fzf.vim' -- Fern に FZF のマッピングを追加

  -- 汎用的な検索と操作用コマンド
  -- use {'mhinz/vim-grepper', opt = true, cmd = {'Grepper', '<plug>(GrepperOperator)', 'GrepperGit'}}
  use {
    'mhinz/vim-grepper',
    opt = true,
    cmd = {'Grepper', '<plug>(GrepperOperator)', 'GrepperGit'},
    setup = function()
      vim.cmd [[
      command! -nargs=* GrepperGit lua require('packer').loader('vim-grepper') | exe 'GrepperGit ' . <q-args>
      ]]
    end,
  }

  -- タグ（関数やクラス）を表示
  use 'majutsushi/tagbar'

  -- Denops を使用したプラグイン補完システム
  use 'Shougo/ddc.vim'
  use 'vim-denops/denops.vim'
  use 'Shougo/ddc-ui-native'
  use 'Shougo/ddc-source-around'
  use 'Shougo/ddc-filter-matcher_head'
  use 'Shougo/ddc-filter-sorter_rank'
  use 'LumaKernel/ddc-source-file'

  -- 簡単な文字列揃え
  use 'junegunn/vim-easy-align'

  -- Node.js 開発のサポート gfでrequreやimportをジャンプ
  use 'moll/vim-node'

  -- JavaScript 開発のサポート
  use 'pangloss/vim-javascript'
  use 'jelera/vim-javascript-syntax'

  -- HTML5 の補完や構文サポート
  use 'othree/html5.vim'

  -- タグリストの操作
  use 'vim-scripts/taglist.vim'

  -- インデントガイドを表示
  use 'Yggdroot/indentLine'

  -- Rails アプリのユナイトインターフェース
  use 'basyura/unite-rails'

  -- コメントアウト操作を簡単に
  -- gcc でコメントと解除を切り替え
  use 'tomtom/tcomment_vim'

  -- 高速検索とファイル操作
  use {'junegunn/fzf', run = './install --all'} -- FZF コマンドラインツール
  use 'junegunn/fzf.vim' -- FZF の Vim インターフェース

  -- Telescope フレームワーク
  use 'nvim-telescope/telescope.nvim'

  -- Git 差分表示 編集行の左側に表示
  use 'airblade/vim-gitgutter'

  -- Git 操作を統合 :Git blame :Git diff :Git log
  use 'tpope/vim-fugitive'

  -- コード構文解析とハイライト強化
  use {'nvim-treesitter/nvim-treesitter', run = ':TSUpdate'}
  use 'nvim-treesitter/nvim-treesitter-context' -- 関数名やクラス名を画面上部に表示

  -- ctrl + j or k 縦移動 現在位置から縦に次の文字がある場所へ移動する
  use 'haya14busa/vim-edgemotion'

  -- TypeScript 開発のサポート
  use 'leafgarland/typescript-vim'
  use 'peitalin/vim-jsx-typescript'

  -- デバッグツールと VSCode 用デバッグアダプター
  use 'mfussenegger/nvim-dap'
  use 'mxsdev/nvim-dap-vscode-js'

  -- 初回インストール
  if packer_bootstrap then
    require('packer').sync()
  end
end)
