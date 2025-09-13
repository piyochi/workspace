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
  { "tomtom/tcomment_vim", lazy = false },

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
        highlight = { enable = true },
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

      -- 共通 on_attach: tsserver/solargraph のみフォーマットを無効化
      local function on_attach_common(client, bufnr)
        if client.name == "tsserver" or client.name == "solargraph" then
          client.server_capabilities.documentFormattingProvider = false
          client.server_capabilities.documentRangeFormattingProvider = false
        end
      end

      -- TypeScript 用の LSP サーバー 事前にnpm install -g typescript-language-server
      lspconfig.ts_ls.setup {
        on_attach = function(client, bufnr)
          on_attach_common(client, bufnr)
          vim.keymap.set("n", "gd", vim.lsp.buf.definition, { buffer = bufnr })
          vim.keymap.set("n", "gr", vim.lsp.buf.references, { buffer = bufnr })
          vim.keymap.set("n", "K", vim.lsp.buf.hover, {})
        end,
      }
      -- Ruby 用の LSP サーバー 事前にgem install solargraph
      lspconfig.solargraph.setup {
        on_attach = function(client, bufnr)
          on_attach_common(client, bufnr)
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
    branch = "main",
    dependencies = {
      { "github/copilot.vim" }, -- or zbirenbaum/copilot.lua
      { "nvim-lua/plenary.nvim" }, -- for curl, log wrapper
    },
    build = "make tiktoken", -- Only on MacOS or Linux
  },

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

  -- AI IDE \at でAI用のプロンプトを表示
  -- cargo を使えるようにしておく
  --   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
  {
    "yetone/avante.nvim",
    event = "VeryLazy",
    lazy = false,
    version = false, -- set this if you want to always pull the latest change
    opts = function()
      -- Copilot を使う前提（OpenAI等にしたい場合は provider を変更）
      local mcp = require("mcphub")
      return {
        provider = "copilot",
        providers = {
          copilot = {
            model = "claude-sonnet-4",   -- 3.7/3.5 を使うならここを変更
            -- 他に必要な項目があればここへ
          },
          -- openai = { model = "gpt-4o-mini", ... },
          -- gemini = { model = "gemini-1.5-flash-latest", ... },
        },
        -- ★ MCP の“System Prompt”を Avante に注入（有効サーバの定義を下敷きに）
        system_prompt = function()
          local hub = mcp.get_hub_instance()
          return hub and hub:get_active_servers_prompt() or ""
        end,
        -- ★ MCP ツールを Avante の Tools に1本差し込む
        custom_tools = function()
          local ok, ext = pcall(require, "mcphub.extensions.avante")
          return ok and { ext.mcp_tool() } or {}
        end,
        behaviour = {
          auto_suggestions = true,
          auto_set_highlight_group = true,
          auto_set_keymaps = true,
          auto_apply_diff_after_generation = true,
          support_paste_from_clipboard = true,
        },
        windows = {
          position = "right",
          width = 40,
          wrap = true,
          sidebar_header = {
            align = "center",
            rounded = false,
          },
          input = {
            prefix = "> ",
            height = 15,
          },
          ask = {
            floating = true,
            start_insert = true,
            border = "single",
          },
        },
      }
    end,
    -- opts = {
    --   provider = 'openai',
    --   -- provider = 'gemini',
    --   openai = {
    --     model = "gpt-4o-mini",
    --     temperature = 0.7,
    --     max_tokens = 4096,
    --   },
    --   gemini = {
    --     model = "gemini-1.5-flash-latest",
    --     temperature = 0.7,
    --     max_tokens = 4096,
    --   },
    --   behaviour = {
    --     auto_suggestions = true,
    --     auto_set_highlight_group = true,
    --     auto_set_keymaps = true,
    --     auto_apply_diff_after_generation = true,
    --     support_paste_from_clipboard = true,
    --   },
    --   windows = {
    --     position = "right",
    --     width = 30,
    --     sidebar_header = {
    --       align = "center",
    --       rounded = false,
    --     },
    --     ask = {
    --       floating = true,
    --       start_insert = true,
    --       border = "rounded"
    --     }
    --   },
    -- },
    -- if you want to build from source then do `make BUILD_FROM_SOURCE=true`
    build = "make",
    -- build = "powershell -ExecutionPolicy Bypass -File Build.ps1 -BuildFromSource false" -- for windows
    dependencies = {
      "nvim-treesitter/nvim-treesitter",
      "stevearc/dressing.nvim",
      "nvim-lua/plenary.nvim",
      "MunifTanjim/nui.nvim",
      --- The below dependencies are optional,
      "nvim-tree/nvim-web-devicons", -- or echasnovski/mini.icons
      "zbirenbaum/copilot.lua", -- for providers='copilot'
      {
        -- support for image pasting
        "HakonHarnes/img-clip.nvim",
        event = "VeryLazy",
        opts = {
          -- recommended settings
          default = {
            embed_image_as_base64 = false,
            prompt_for_file_name = false,
            drag_and_drop = {
              insert_mode = true,
            },
            -- required for Windows users
            use_absolute_path = true,
          },
        },
      },
      -- AI用プロンプトのカラー調整だがnvim-lspconfigも変わる
      -- rloginだと色が合わず見難いため使わない
      -- macだと良い感じなので環境含めてどうするか要検討
      -- {
      --   -- Make sure to set this up properly if you have lazy=true
      --   'MeanderingProgrammer/render-markdown.nvim',
      --   opts = {
      --     file_types = { "markdown", "Avante" },
      --   },
      --   ft = { "markdown", "Avante" },
      -- },
    },
  },
  --- MCP
  {
    "ravitemer/mcphub.nvim",
    dependencies = { "nvim-lua/plenary.nvim" },
    cmd = { "MCPHub" },
    build = "npm install -g mcp-hub@latest",
    event = "VeryLazy",
    config = function()
      require("mcphub").setup({
        -- デフォルトで ~/.config/mcphub/servers.json を読む
        -- 必要なら env 共有などもここで設定可
        -- global_env = { "GITHUB_MCP_PAT" },
        -- まずツール承認ダイアログを省く（UI呼び出しを減らす意味でも有効）
        auto_approve = true,

        -- ★ ここが本丸：フロートの枠を 1セル幅に固定（エラー回避）
        ui = {
          window  = { border = "single" },
          confirm = { border = "single" },
          input   = { border = "single" },
          select  = { border = "single" },
          preview = { border = "single" },
        },

        extensions = {
          avante = {
            enabled = true,
            make_slash_commands = true, -- prompts を持つサーバ用（GitHubはtools中心なので出なくても正常）
          },
        },
      })
    end,
    -- opts = {
    --   -- ツール実行の都度の確認ダイアログを省きたい場合は true（UI からも a キーで切替可）
    --   -- auto_approve = true,
    --   extensions = {
    --     avante = {
    --       enabled = true,
    --       make_slash_commands = true,  -- /mcp:github:... みたいなスラコマを自動生成
    --     },
    --     -- 枠をASCIIに固定（確実に1セル）
    --     ui = {
    --       -- 好みで "single" でもOKだが、確実性重視で明示
    --       border = { "+","-","+","|","+","-","+","|" },   -- tl, t, tr, r, br, b, bl, l
    --       input  = { border = { "+","-","+","|","+","-","+","|" } },
    --       select = { border = { "+","-","+","|","+","-","+","|" } },
    --     },
    --   },
    -- },
  },
}, {
  -- 全プラグインを遅延ロード
  defaults = {
    lazy = true,
  },
})

