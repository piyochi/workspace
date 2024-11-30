-- lazy.nvimを自動インストール
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.loop.fs_stat(lazypath) then
  vim.fn.system({
    "git",
    "clone",
    "--filter=blob:none",
    "https://github.com/folke/lazy.nvim.git",
    "--branch=stable", -- 最新安定版
    lazypath,
  })
end
vim.opt.rtp:prepend(lazypath)

-- lazy.nvimの初期設定
require("lazy").setup({
  -- 必須の依存プラグイン
  { "nvim-lua/plenary.nvim" },

  -- 検索結果を操作するためのプラグイン
  { "vim-scripts/grep.vim", cmd = { "Grep" }},

  -- Rails アプリ開発をサポート
  { "tpope/vim-rails", event = { "CmdlineEnter" }},

  -- ファイルツリー表示と操作
  { "lambdalisue/fern.vim", cmd = { "Fern" }},

  -- 汎用的な検索と操作用コマンド
  {
    "mhinz/vim-grepper",
    lazy = true,
    cmd = { "Grepper", "GrepperGit", "GrepperGrep" },
    init = function()
      vim.api.nvim_create_user_command("GrepperGit", function(args)
        require("lazy").load({ plugins = { "vim-grepper" } })
        vim.cmd("GrepperGit " .. args.args)
      end, { nargs = "*" })
    end,
  },

  -- Denops を使用したプラグイン補完システム
  {
    "Shougo/ddc.vim",
    dependencies = {
      "vim-denops/denops.vim",             -- Denops の依存プラグイン
      "Shougo/ddc-source-around",         -- `around` ソース
      "Shougo/ddc-ui-native",             -- UI の設定
      "Shougo/ddc-filter-matcher_head",   -- 補完のマッチャー
      "Shougo/ddc-filter-sorter_rank",    -- 補完結果のソート
      "LumaKernel/ddc-source-file",       -- ファイル補完ソース
    },
    lazy = false, -- 起動時にロード
    config = function()
      vim.fn["ddc#custom#patch_global"]({
        sources = { "around", "file" }, -- 使用するソース
        sourceOptions = {
          _ = {
            matchers = { "matcher_head" },
            sorters = { "sorter_rank" },
          },
        },
      })
      -- ddc.vim の有効化
      vim.cmd([[call ddc#enable()]])
    end,
  },

  -- 簡単な文字列揃え
  { "junegunn/vim-easy-align", cmd = { "EasyAlign" }},

  -- Node.js 開発のサポート gfでrequireやimportをジャンプ
  { "moll/vim-node", lazy = false},

  -- JavaScript 開発のサポート
  { "pangloss/vim-javascript", lazy = false},
  { "jelera/vim-javascript-syntax", lazy = false},

  -- HTML5 の補完や構文サポート
  { "othree/html5.vim", lazy = false},

  -- タグリストの操作 F8
  { "majutsushi/tagbar", lazy = false },

  -- インデントガイドを表示
  { "Yggdroot/indentLine", lazy = false },

  -- コメントアウト操作を簡単に
  -- gcc でコメントと解除を切り替え
  { "tomtom/tcomment_vim" },

  -- 高速検索とファイル操作
  { "junegunn/fzf", build = "./install --all", lazy = false }, -- FZF コマンドラインツール
  { "junegunn/fzf.vim", event = { "CmdlineEnter" }}, -- FZF の Vim インターフェース

  -- Telescope フレームワーク
  { "nvim-telescope/telescope.nvim" },

  -- Git 差分表示 編集行の左側に表示
  { "airblade/vim-gitgutter", lazy = false },

  -- Git 操作を統合 :Git blame :Git diff :Git log
  { "tpope/vim-fugitive", lazy = false },

  -- コード構文解析とハイライト強化
  { "nvim-treesitter/nvim-treesitter", build = ":TSUpdate" },
  { "nvim-treesitter/nvim-treesitter-context" }, -- 関数名やクラス名を画面上部に表示

  -- gf: ファイルを開く gd: 定義にジャンプ gr: 参照を表示 K: ドキュメントを表示
  {
    "neovim/nvim-lspconfig",
    lazy = false,
    config = function()
      local lspconfig = require("lspconfig")

      -- TypeScript 用の LSP サーバー 事前にnpm install -g typescript-language-server
      lspconfig.ts_ls.setup {
        on_attach = function(client, bufnr)
          vim.keymap.set("n", "gd", vim.lsp.buf.definition, { buffer = bufnr })
          vim.keymap.set("n", "gr", vim.lsp.buf.references, { buffer = bufnr })
          vim.keymap.set("n", "K", vim.lsp.buf.hover, {})
        end,
      }
      -- Ruby 用の LSP サーバー 事前にgem install solargraph
      lspconfig.solargraph.setup {
        on_attach = function(client, bufnr)
          vim.keymap.set("n", "gd", vim.lsp.buf.definition, { buffer = bufnr })
          vim.keymap.set("n", "gr", vim.lsp.buf.references, { buffer = bufnr })
          vim.keymap.set("n", "K", vim.lsp.buf.hover, {})
        end,
      }
    end,
  },

  -- ctrl + j or k 縦移動 現在位置から縦に次の文字がある場所へ移動する
  { "haya14busa/vim-edgemotion", lazy = false },

  -- TypeScript 開発のサポート
  -- { "leafgarland/typescript-vim"}, -- 構文ハイライトだがなくても変わらなかったためコメントアウト
  -- { "peitalin/vim-jsx-typescript" }, -- 構文ハイライトだがなくても変わらなかったためコメントアウト

  -- ファイル保存時にeslintとprettierを自動実行
  {
    "nvimtools/none-ls.nvim",
    lazy = false,
    dependencies = { "nvim-lua/plenary.nvim", "nvimtools/none-ls-extras.nvim" },
  },
  { "prettier/eslint-plugin-prettier", lazy = false },

  -- GitHub Copilotのチャット機能
  {
    "CopilotC-Nvim/CopilotChat.nvim",
    branch = "canary",
    dependencies = {
      { "github/copilot.vim" }, -- or zbirenbaum/copilot.lua
      { "nvim-lua/plenary.nvim" }, -- for curl, log wrapper
    },
    build = "make tiktoken", -- Only on MacOS or Linux
  },
}, {
  -- 全プラグインを遅延ロード
  defaults = {
    lazy = true,
  },
})

