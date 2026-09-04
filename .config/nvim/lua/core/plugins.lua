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

  -- Nerd Font アイコン表示
  { "lambdalisue/nerdfont.vim", lazy = false },
  -- ファイルツリー表示と操作
  {
    "lambdalisue/fern.vim",
    cmd = { "Fern" },
  },
  {
    "lambdalisue/fern-renderer-nerdfont.vim",
    dependencies = { "lambdalisue/fern.vim", "lambdalisue/nerdfont.vim" },
    lazy = false,
  },
  { "lambdalisue/fern-git-status.vim", lazy = false },

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
    -- 設定は lua/plugins/ddc.lua に集約（init.lua から require される）。
    -- ここにも config を書くと二重設定になるため置かない
  },

  -- 簡単な文字列揃え
  { "junegunn/vim-easy-align", cmd = { "EasyAlign" }},

  -- タグリストの操作 F8
  { "majutsushi/tagbar", lazy = false },

  -- インデントガイドを表示
  { "lukas-reineke/indent-blankline.nvim",
    main = "ibl",
    opts = {
      indent = { char = "┆", highlight = "IblIndent" },
      scope = {
        enabled = true,
        -- show_start = true, -- 開始行をうっすら強調
        highlight = "IblScope",
        include = {
          node_type = {
            ruby = {
              -- 定義/構造
              "class", "module", "method",
              -- ブロック
              "block", "do_block",
              -- 制御構文
              "if", "if_modifier", "elsif", "unless", "unless_modifier",
              "case", "when", "while", "until", "for",
              "begin", "rescue", "ensure",
            },
            javascript = {
              "function", "function_declaration", "function_expression",
              "method_definition", "class_declaration",
              "arrow_function", "statement_block", "object", "array",
            },
            typescript = {
              "function", "function_declaration", "function_signature",
              "method_definition", "class_declaration",
              "arrow_function", "statement_block", "object", "array", "module",
            },
            -- React/JSX 系
            javascriptreact = {
              "arrow_function", "function_declaration", "method_definition",
              "jsx_element", "jsx_self_closing_element", "jsx_fragment",
              "statement_block",
            },
            typescriptreact = {
              "arrow_function", "function_declaration", "method_definition",
              "jsx_element", "jsx_self_closing_element", "jsx_fragment",
              "statement_block",
            },
            tsx = {  -- 一部の環境では filetype=tsx を見ることもある
              "arrow_function", "function_declaration", "method_definition",
              "jsx_element", "jsx_fragment", "statement_block",
            },
          },
        },
      },
      exclude = {
        filetypes = { "help", "terminal", "dashboard" },
        buftypes = { "terminal" },
      },
    },
    config = function(_, opts)
      local hooks = require("ibl.hooks")
      hooks.register(hooks.type.HIGHLIGHT_SETUP, function()
        vim.api.nvim_set_hl(0, "IblIndent", { fg = "#444444", nocombine = true })
        vim.api.nvim_set_hl(0, "IblScope",  { fg = "#CCCCCC", nocombine = true })
      end)

      require("ibl").setup(opts)
    end,
    lazy = false,
  },

  -- コメントアウト操作を簡単に
  -- gcc でコメントと解除を切り替え
  { "tomtom/tcomment_vim", lazy = false },

  -- Telescope フレームワーク
  { "nvim-telescope/telescope.nvim" },

  -- Git 差分表示 編集行の左側に表示
  { "airblade/vim-gitgutter", lazy = false },

  -- Git 操作を統合 :Git blame :Git diff :Git log
  { "tpope/vim-fugitive", lazy = false },

  -- コード構文解析とハイライト強化
  { "nvim-treesitter/nvim-treesitter", build = ":TSUpdate" },
  {
    "nvim-treesitter/nvim-treesitter-context", -- 関数名やクラス名を画面上部に表示
    build = ":TSUpdate",
    init = function()
      local dir = vim.fn.stdpath("data") .. "/parsers"
      -- 起動直後に runtimepath へ追加（setup より前に）
      if not string.find(table.concat(vim.opt.runtimepath:get(), ","), dir, 1, true) then
        vim.opt.runtimepath:append(dir)
      end
    end,
    config = function()
      local dir = vim.fn.stdpath("data") .. "/parsers"
      require("nvim-treesitter.configs").setup({
        parser_install_dir = dir,
        ensure_installed = { "lua","javascript","python","ruby","go","typescript","tsx","json","html","css","markdown" },
        highlight = {
          enable = true,
          disable = {
            'markdown', -- ```とかでリアルタイムプレビューして見にくくなるので無効化
          },
        },
        -- gg=G 等の = による再インデントを treesitter に任せる。
        -- nvim標準の GetTypescriptIndent() は JSX を理解できず、
        -- tsx の入れ子(<div>→<span>)が全て同じ深さに潰れて4スペースになる。
        -- treesitter なら .prettierrc の tabWidth:2 と一致した階層で再現できる。
        -- ※ 公式に experimental 扱い。崩れる言語が出たら disable = { "言語" } で除外する
        indent = { enable = true },
        auto_install = false, -- 勝手な再インストールを止める
        sync_install = false,
      })
    end,
  },

  -- gf: ファイルを開く gd: 定義にジャンプ gr: 参照を表示 K: ドキュメントを表示
  {
    "neovim/nvim-lspconfig",
    lazy = false,
    config = function()
      local lspconfig = require("lspconfig")

      -- 共通 on_attach: ts_ls/solargraph のみフォーマットを無効化
      -- (フォーマットは none-ls の prettier / eslint / rubocop に任せる)
      -- ※ nvim-lspconfig で tsserver は ts_ls に改名済み。旧名のままだと判定が発火せず
      --   ts_ls がフォーマッタとして名乗り出て prettier と競合する
      local function on_attach_common(client, bufnr)
        if client.name == "ts_ls" or client.name == "solargraph" then
          client.server_capabilities.documentFormattingProvider = false
          client.server_capabilities.documentRangeFormattingProvider = false
        end

        -- ※ g]/<C-]> を ctags に固定する処理は core/settings.lua の tagfunc 側で行う。
        -- ここで tagfunc を空に戻してもサーバ初期化完了時に再度奪われる
      end

      -- TypeScript 用の LSP サーバー 事前にnpm install -g typescript-language-server
      -- 未インストール環境では起動失敗の "Press ENTER" が毎回出るので実行可能かで判定する
      if vim.fn.executable("typescript-language-server") == 1 then
        lspconfig.ts_ls.setup {
          on_attach = function(client, bufnr)
            on_attach_common(client, bufnr)
            vim.keymap.set("n", "gd", vim.lsp.buf.definition, { buffer = bufnr })
            vim.keymap.set("n", "gr", vim.lsp.buf.references, { buffer = bufnr })
            vim.keymap.set("n", "K", vim.lsp.buf.hover, {})
          end,
        }
      end
      -- Ruby 用の LSP サーバー 事前にgem install solargraph
      if vim.fn.executable("solargraph") == 1 then
        lspconfig.solargraph.setup {
          on_attach = function(client, bufnr)
            on_attach_common(client, bufnr)
            vim.keymap.set("n", "gd", vim.lsp.buf.definition, { buffer = bufnr })
            vim.keymap.set("n", "gr", vim.lsp.buf.references, { buffer = bufnr })
            vim.keymap.set("n", "K", vim.lsp.buf.hover, {})
          end,
        }
      end
    end,
  },

  -- ctrl + j or k 縦移動 現在位置から縦に次の文字がある場所へ移動する
  { "haya14busa/vim-edgemotion", lazy = false },

  -- ファイル保存時にeslintとprettierを自動実行
  {
    "nvimtools/none-ls.nvim",
    lazy = false,
    dependencies = { "nvim-lua/plenary.nvim", "nvimtools/none-ls-extras.nvim" },
  },

  -- GitHub Copilot のインライン補完
  -- <Tab>で確定 / <C-]>で却下 / <M-]><M-[>で候補送り / \cpでトグル
  -- (チャット系のAIプラグインは Claude Code に移行したため削除済み)
  { "github/copilot.vim", lazy = false },

  -- \u で変更履歴を表示
  {
    "jiaoshijie/undotree",
    dependencies = "nvim-lua/plenary.nvim",
    config = function()
      require("undotree").setup({
        window = {
          winblend = 0, -- ウィンドウの透明度を調整
        },
      })
    end,
    keys = {
      { "<leader>u", "<cmd>lua require('undotree').toggle()<cr>" },
    },
  },

}, {
  -- 全プラグインを遅延ロード
  defaults = {
    lazy = true,
  },
})

