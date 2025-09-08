local MAX_PROMPT_LINES    = 800  -- プロンプトが長すぎる場合の最大行数

-- ANSIカラーコードを除去（例: \x1b[31m）
local function strip_ansi(s)
  return s:gsub("\27%[[0-9;]*[A-Za-z]", "")
end

-- 非UTF-8バイトを安全に除去（不正シーケンスは "?" に置換）
local function ensure_valid_utf8(s)
  if type(s) ~= "string" then
    return tostring(s)
  end

  local out = {}
  local i, len = 1, #s
  while i <= len do
    local b = s:byte(i)
    if not b then break end

    local n =
    (b < 0x80 and 1)
    or (b >= 0xC2 and b < 0xE0 and 2)
    or (b >= 0xE0 and b < 0xF0 and 3)
    or (b >= 0xF0 and b < 0xF5 and 4)
    or 1

    if i + n - 1 > len then
      table.insert(out, "?")
      i = i + 1
    else
      local chunk = s:sub(i, i + n - 1)
      local valid = true

      if n == 1 then
        if b >= 0x80 then valid = false end
      else
        for j = 2, n do
          local cb = s:byte(i + j - 1)
          if not cb or cb < 0x80 or cb > 0xBF then valid = false; break end
        end
      end

      if valid then
        table.insert(out, chunk)
        i = i + n
      else
        table.insert(out, "?")
        i = i + 1
      end
    end
  end
  return table.concat(out)
end

-- 長すぎるテキストを先頭 N 行にトリム。戻り値: (text, was_truncated)
local function head_lines(text, max_lines)
  local out, cnt = {}, 0
  for line in text:gmatch("[^\r\n]+") do
    cnt = cnt + 1
    table.insert(out, line)
    if cnt >= max_lines then
      table.insert(out, "... (truncated)")
      return table.concat(out, "\n"), true
    end
  end
  return table.concat(out, "\n"), false
end

-- 共通のプロンプト送信ロジックを関数化
local function send_prompt(base_prompt, opts, confirmation_config)
  -- 確認処理がある場合
  if confirmation_config then
    local confirmation_message = confirmation_config.message or "実行してもよろしいですか？"
    local choice = vim.fn.confirm(confirmation_message, "&Yes\n&No", 2)

    if choice ~= 1 then
      print("キャンセルされました。")
      return
    end
  end

  local prompt = base_prompt

  -- 範囲が指定されている場合、その範囲のテキストを取得
  if opts.range == 2 then
    local lines = vim.api.nvim_buf_get_lines(0, opts.line1 - 1, opts.line2, false)
    local selected_text = table.concat(lines, "\n")
    prompt = prompt .. "\n" .. selected_text
  end

  -- プロンプト全体の安全性チェック（UTF-8検証を先に実行）
  prompt = ensure_valid_utf8(prompt)
  prompt = strip_ansi(prompt)

  -- プロンプトが長すぎる場合のチェック
  local truncated, was_truncated = head_lines(prompt, MAX_PROMPT_LINES)
  prompt = truncated

  if was_truncated then
    vim.notify(
      ("⚠️ プロンプトが長すぎるため先頭 %d 行のみ送信しました"):format(MAX_PROMPT_LINES),
      vim.log.levels.WARN
    )
  end

  -- 最終的な安全性チェック
  if not vim.fn.has('nvim-0.7') or pcall(vim.validate, { prompt = { prompt, 'string' } }) then
    -- AIにプロンプトを送信
    require("avante.api").ask(prompt)
  else
    vim.notify("⚠️ プロンプトに無効な文字が含まれています", vim.log.levels.ERROR)
  end
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

-- RSpec自動作成コマンド（gitの差分から変更ファイルを特定し、そのファイルに対応するRSpecを自動生成・修正）
-- :AiGeneratorRSpec {args}   例) :AiGeneratorRSpec --last 3   /   :AiGeneratorRSpec --since-branch master
vim.api.nvim_create_user_command("AiGeneratorRSpec", function(opts)
  local diff_args = (opts.args ~= "" and opts.args) or "--last 1 --only-app"

  local prompt = string.format([[
あなたはこのリポの「RSpec自動化コーチ」です。bash ツールと編集ツールを使い、各ステップの結果を要約しながら進めてください。破壊的コマンドは禁止。生成パッチはプレビュー提示（自動適用しない）でお願いします。
説明はすべて日本語で。以下の前提と方針を厳守してください。

【前提（違反なら即停止・報告）】
- ai_tooling/avante/check-preconditions.sh を実行し、次を満たすことを確認：
  1) git が完全クリーン（git status --porcelain が空）
  2) Rubocop 全体がパス
  3) RSpec 全体がパス
  ※ どれかNGなら以降の処理を行わず停止・報告。

【対象】
- 直前コミット（HEAD^..HEAD）の *.rb（spec/ を除外）。対象が0件なら終了を報告。
- 変更ファイル一覧の取得は ai_tooling/avante/changed-ruby-files.sh を使用。

【RSpec作成/更新方針（app/配下の型と spec 置き場を厳守）】
- app/models/**.rb      → spec/models/**_spec.rb        （type: :model）
- app/controllers/**.rb  → spec/controllers/**_spec.rb   （type: :controller）
- app/mailers/**.rb      → spec/mailers/**_spec.rb       （type: :mailer）
- app/services/**.rb     → spec/services/**_spec.rb      （type: :service）
- app/workers/**.rb      → spec/workers/**_spec.rb       （type: :worker）
※ 既存の spec がある場合は不足ケースを**追記・修正**（大規模な全面置換は避ける）。
※ Factory/stub/mock は最小限。アプリ本体（app/**）の修正は原則禁止。必要時は私に相談。
※ derscribeはメソッド名等のプログラム名称を記載してください。controllerなら'GET #index'という感じに、他のメソッドは'#self.reset_sort_order!'という感じで。
※ it/context は日本語で記載してください。

【Rubocopの扱い（常にクリーン維持）】
- spec を編集するたびに Rubocop を spec に対して実行。自動整形で直せるものは直し、残ればテストコード側を修正してパスさせる。
  - ai_tooling/avante/run-rubocop.sh --fix spec

【実行ループ】
1) 前提チェック（上記スクリプト）— NGなら即停止
2) 変更Ruby一覧の取得 → 対象0なら終了
3) 各ファイルの仕様要約 → 該当 spec を新規作成/追記（上記マッピング & type厳守）
4) Rubocop（--fix spec）を実行 → なお違反があれば修正して再実行
5) RSpec 実行：ai_tooling/avante/run-rspec.sh
6) 失敗があれば失敗内容を要約 → **最小変更**で spec を修正（必要ならFactory/stub追加）→ 4)→5) を繰り返す
7) すべてグリーンかつ Rubocop 0 で終了。作成/更新した spec の一覧と要点を報告

まず 1) の前提チェックを実行して結果を報告。OKなら 2) に進んでください。
]], diff_args)

  -- bang（!）が付いていない場合のみ確認処理を追加
  local confirmation_config = nil
  if not opts.bang then
    confirmation_config = {
      message = "RSpec修正を実行します。\nこれによりspecファイルの自動作成/修正が行われます。\n実行してもよろしいですか？"
    }
  end

  send_prompt(prompt, opts, confirmation_config)
end, {
  nargs = "*",
  bang = true,
  complete = function()
    return { "--last", "--vs", "--since-branch", "--range", "--commits", "--only-app" }
  end,
})

-- :AiUpdateRSpec {args}
-- 例) :AiUpdateRSpec           （全体）
--     :AiUpdateRSpec spec/models/user_spec.rb:42
--     :AiUpdateRSpec --profile
vim.api.nvim_create_user_command("AiUpdateRSpec", function(opts)
  local rspec_args = opts.args or ""
  local prompt = string.format([[
あなたはこのリポの「RSpec修復コーチ」です。bash ツールと編集ツールを使い、各ステップの結果を要約しながら進めてください。破壊的コマンドは禁止。生成パッチはプレビュー提示（自動適用しない）でお願いします。
説明はすべて日本語で。以下の前提と方針を厳守してください。

【ゴール】既存の RSpec をグリーンにする。原則として app/** は変更しない（必要な場合は理由を述べて私の許可を取る）。

【前提（違反なら即停止・報告）】
- ai_tooling/avante/check-preconditions.sh git を実行し、次を満たすことを確認：
  1) git が完全クリーン（git status --porcelain が空）

【RSpec更新方針（app/配下の型と spec 置き場を厳守）】
- app/models/**.rb      → spec/models/**_spec.rb        （type: :model）
- app/controllers/**.rb  → spec/controllers/**_spec.rb   （type: :controller）
- app/mailers/**.rb      → spec/mailers/**_spec.rb       （type: :mailer）
- app/services/**.rb     → spec/services/**_spec.rb      （type: :service）
- app/workers/**.rb      → spec/workers/**_spec.rb       （type: :worker）
※ Factory/stub/mock は最小限。アプリ本体（app/**）の修正は原則禁止。必要時は私に相談。
※ derscribeはメソッド名等のプログラム名称を記載してください。controllerなら'GET #index'という感じに、他のメソッドは'#self.reset_sort_order!'という感じで。
※ it/context は日本語で記載してください。

【手順】
1) RSpec を実行： ai_tooling/avante/run-rspec.sh %s
   - 成功(終了コード0)なら「既にグリーン」と報告して終了。
   - 失敗なら、失敗例/エラーを要約して次へ。

2) 失敗原因に対して、既存の spec を最小変更で修正（不足の context / example / expect の追加、必要最小限の stub/mock/Factory の補完）。
   - app/** の変更は原則禁止。やむを得ない場合は必ず私に確認。

3) Rubocop を spec に対して適用： ai_tooling/avante/run-rubocop.sh --fix spec
   - なお違反が残る場合はテストコード側を修正して解消。

4) 再度 RSpec を実行（同コマンド）。グリーンになるまで 2)〜4) を繰り返す。

5) 終了時に、更新/作成した spec の一覧と要点を報告する。
]], rspec_args)

  -- bang（!）が付いていない場合のみ確認処理を追加
  local confirmation_config = nil
  if not opts.bang then
    confirmation_config = {
      message = "RSpec修正を実行します。\nこれによりspecファイルの自動作成/修正が行われます。\n実行してもよろしいですか？"
    }
  end

  send_prompt(prompt, opts, confirmation_config)
end, {
  nargs = "*",
  bang = true,
})

-- :AiUpdateRubocop {args}
-- 例) :AiUpdateRubocop            （既定: spec/ を対象）
--     :AiUpdateRubocop --all      （リポ全体）
--     :AiUpdateRubocop app/services app/models/user.rb
vim.api.nvim_create_user_command("AiUpdateRubocop", function(opts)
  local scope = (opts.args ~= "" and opts.args) or "spec"
  local prompt = string.format([[
あなたはこのリポの「Rubocop整備コーチ」です。以下を実施してください（破壊的コマンド禁止、生成パッチはプレビュー提示）。
説明はすべて日本語で。以下の前提と方針を厳守してください。

【対象スコープ】%s
- "--all" または "." を指定した場合、app/** を含む全体を対象にしてよいが、挙動を変えない安全な修正を最優先とする。必要なら私に確認を取る。

【前提（違反なら即停止・報告）】
- ai_tooling/avante/check-preconditions.sh git を実行し、次を満たすことを確認：
  1) git が完全クリーン（git status --porcelain が空）

【手順】
1) 現状確認： ai_tooling/avante/run-rubocop.sh %s
   - 終了コードが非0なら次へ。

2) 自動整形： ai_tooling/avante/run-rubocop.sh --fix %s

3) なお違反が残る場合は、対象スコープ内のファイルを最小変更で修正して解消。
   - ルール無効化コメントは最終手段。入れる場合は理由をコメントで明記。

4) 最終確認： ai_tooling/avante/run-rubocop.sh %s を再実行し、終了コード0を確認。
   - 変更点の要約と、恒久的に設定した方が良いルールがあれば提案も出す。
]], scope, scope, scope, scope)

  send_prompt(prompt, { confirm = true, new_chat = true })
end, {
  nargs = "*",
  bang = true,
  complete = function() return { "--all" } end,
})
