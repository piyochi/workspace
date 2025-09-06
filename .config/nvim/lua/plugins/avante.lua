-- 共通のプロンプト送信ロジックを関数化
local function send_prompt(base_prompt, opts)
  local prompt = base_prompt

  -- 範囲が指定されている場合、その範囲のテキストを取得
  if opts.range == 2 then
    local lines = vim.api.nvim_buf_get_lines(0, opts.line1 - 1, opts.line2, false)
    local selected_text = table.concat(lines, "\n")
    prompt = prompt .. "\n" .. selected_text
  end

  -- AIにプロンプトを送信
  require("avante.api").ask(prompt)
end

-- コマンド定義: コード説明
vim.api.nvim_create_user_command("AvanteExplain", function(opts)
  send_prompt(
    "コードを日本語で説明してください",
    opts
  )
end, { range = true })

-- コマンド定義: コードレビュー
vim.api.nvim_create_user_command("AvanteReview", function(opts)
  send_prompt(
    "コードの改善点を教えてください。説明は日本語でお願いします。",
    opts
  )
end, { range = true })

-- コマンド定義: コード修正
vim.api.nvim_create_user_command("AvanteFix", function(opts)
  send_prompt(
    "このコードには問題があります。バグを修正したコードを表示してください。説明は日本語でお願いします。",
    opts
  )
end, { range = true })

-- コマンド定義: コード最適化
vim.api.nvim_create_user_command("AvanteOptimize", function(opts)
  send_prompt(
    "選択したコードを最適化し、パフォーマンスと可読性を向上させてください。説明は日本語でお願いします。",
    opts
  )
end, { range = true })

-- コマンド定義: ドキュメント生成
vim.api.nvim_create_user_command("AvanteDocs", function(opts)
  send_prompt(
    "選択したコードに関するドキュメントコメントを日本語で生成してください。",
    opts
  )
end, { range = true })

-- コマンド定義: ユニットテスト生成
vim.api.nvim_create_user_command("AvanteTests", function(opts)
  send_prompt(
    "選択したコードの詳細なユニットテストを書いてください。describeは関数名・メソッド名でそれ以外のitやcontextなどは日本語でお願いします。説明は日本語でお願いします。",
    opts
  )
end, { range = true })

-- コマンド定義: Git差分からテストコード生成
vim.api.nvim_create_user_command("AvanteGitDiffTests", function(opts)
  send_prompt(
    "選択したgitの差分からファイル毎に詳細な変更分のユニットテストを書いてください。describeは関数名・メソッド名でそれ以外のitやcontextなどは日本語でお願いします。説明は日本語でお願いします。",
    opts
  )
end, { range = true })

-- 上記のコマンドを選択するためのフローティングウィンドウを作成
local function create_floating_window(mode)
  -- コマンドのリスト
  local commands = {
    { name = "AvanteTests", description = "テスト自動生成" },
    { name = "AvanteGitDiffTests", description = "git差分からテスト自動生成" },
    { name = "AvanteReview", description = "コードレビュー" },
    { name = "AvanteExplain", description = "コード説明" },
    { name = "AvanteFix", description = "コード修正" },
    { name = "AvanteOptimize", description = "コード最適化" },
    { name = "AvanteDocs", description = "ドキュメント生成" },
  }

  -- バッファとウィンドウを作成
  local buf = vim.api.nvim_create_buf(false, true) -- 新しいバッファを作成
  local win = vim.api.nvim_open_win(buf, true, {
    relative = "editor",
    width = 60,
    height = #commands, -- リストの行数に合わせて高さを設定
    row = math.floor((vim.o.lines - #commands) / 2),
    col = math.floor((vim.o.columns - 50) / 2),
    border = "rounded",
  })

  -- コマンドリストを表示
  local lines = {}
  for _, cmd in ipairs(commands) do
    table.insert(lines, string.format("  %s - %s", cmd.name, cmd.description))
  end
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)

  -- バッファ設定
  vim.api.nvim_buf_set_option(buf, "modifiable", false)
  vim.api.nvim_buf_set_option(buf, "buftype", "nofile")
  vim.api.nvim_buf_set_option(buf, "bufhidden", "wipe")

  -- 現在の選択位置（初期値は1行目）
  local ns_id = vim.api.nvim_create_namespace("floating_window")
  local current_line = 1

  -- ハイライト設定
  local function update_highlight()
    vim.api.nvim_buf_clear_namespace(buf, ns_id, 0, -1)
    vim.api.nvim_buf_add_highlight(buf, ns_id, "Visual", current_line - 1, 0, -1)
  end
  update_highlight()

  -- ビジュアルモードの範囲取得
  local function get_visual_selection()
    local _, start_row, start_col, _ = unpack(vim.fn.getpos("'<"))
    local _, end_row, end_col, _ = unpack(vim.fn.getpos("'>"))

    -- 選択範囲のテキストを取得
    local lines = vim.api.nvim_buf_get_lines(0, start_row - 1, end_row, false)
    if #lines == 0 then
      return nil
    end

    lines[#lines] = string.sub(lines[#lines], 1, end_col)
    lines[1] = string.sub(lines[1], start_col)
    return table.concat(lines, "\n")
  end

  -- コマンド実行
  local function execute_command()
    local cmd = commands[current_line]
    vim.api.nvim_win_close(win, true)

    -- ビジュアルモードの選択範囲を取得
    local selection = get_visual_selection()
    if selection and mode == "visual" then
      vim.cmd(string.format(":'<,'> %s", cmd.name))
    else
      vim.cmd(cmd.name)
    end
  end

  -- キーマッピング
  local function move_down()
    if current_line < #commands then
      current_line = current_line + 1
      update_highlight()
    end
  end

  local function move_up()
    if current_line > 1 then
      current_line = current_line - 1
      update_highlight()
    end
  end

  vim.keymap.set("n", "j", move_down, { buffer = buf, noremap = true, silent = true })
  vim.keymap.set("n", "k", move_up, { buffer = buf, noremap = true, silent = true })
  vim.keymap.set("n", "<CR>", execute_command, { buffer = buf, noremap = true, silent = true })
  vim.keymap.set("n", "q", function()
    vim.api.nvim_win_close(win, true)
  end, { buffer = buf, noremap = true, silent = true })
end
-- vim.api.nvim_create_user_command("AvanteCommandPicker", function(opts)
--   create_floating_window(mode)
-- end, { range = true })
vim.api.nvim_create_user_command("AvanteCommandPicker", function(opts)
  local mode = opts.args -- 引数を取得
  create_floating_window(mode)
end, {
  nargs = 1, -- 引数を1つ受け取る
  complete = function() -- 補完を提供
    return { "normal", "visual" }
  end,
})

-- AvanteCommandPicker キーバインド設定
vim.keymap.set("n", "<leader>aw", ":AvanteCommandPicker normal<CR>", { noremap = true, silent = true, desc = "Pick a command for Avante.nvim" })
vim.keymap.set("v", "<leader>aw", ":<C-u>AvanteCommandPicker visual<CR>", { noremap = true, silent = true, desc = "Pick a command for Avante.nvim" })

-- Avante chat keymaps: \ac / \an / \as
do
  local function map(mode, lhs, rhs, desc)
    vim.keymap.set(mode, lhs, rhs, { noremap = true, silent = true, desc = desc })
  end

  -- 新規チャット ポップアップ
  map("n", "<leader>an", "<Cmd>AvanteChatNew<CR>", "Avante: New Chat")
end

-- --- Avante: <Tab> で画面移動しないようにする -------------------------------
-- Avante の Ask/Chat ウィンドウでプラグインが付ける <Tab> マップを削除。
-- これで nvim-cmp の <Tab> 確定や通常のタブ挿入が効くようになる。
do
  local aug = vim.api.nvim_create_augroup("my_avante_unmap_tab", { clear = true })
  vim.api.nvim_create_autocmd({ "BufEnter", "WinEnter", "FileType" }, {
    group = aug,
    callback = function(ev)
      -- Avante のバッファをゆるく判定（環境差に強い）
      local ft = vim.bo[ev.buf].filetype or ""
      local name = vim.api.nvim_buf_get_name(ev.buf) or ""
      local is_avante =
        ft:match("^avante") or
        name:match("Avante") or
        name:match("Ask") or
        vim.bo[ev.buf].buftype == "nofile"

      if not is_avante then return end

      -- <Tab> を奪っているローカルマップを消す（あってもなくても OK）
      pcall(vim.keymap.del, "i", "<Tab>", { buffer = ev.buf })
      pcall(vim.keymap.del, "n", "<Tab>", { buffer = ev.buf })
      pcall(vim.keymap.del, "v", "<Tab>", { buffer = ev.buf })
      -- これでウィンドウ移動はデフォの <C-w> 系のみになります
    end,
  })
end
