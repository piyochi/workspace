-- Tagbarの設定
vim.g.tagbar_ctags_bin = "/opt/homebrew/bin/ctags" -- ctags のバイナリパスを設定

-- F8キーでTagbarをトグル
vim.api.nvim_set_keymap("n", "<F8>", ":TagbarToggle<CR>", { noremap = true, silent = true })

-- Tagbarのカスタム設定
vim.g.tagbar_width = 30 -- Tagbarの幅を設定
vim.g.tagbar_sort = 1   -- アルファベット順にソート
vim.g.tagbar_autoclose = 1 -- タグリストが唯一のウィンドウの場合に閉じる
vim.g.tagbar_autofocus = 1 -- タグリストを開いたときにフォーカスを自動で移動

