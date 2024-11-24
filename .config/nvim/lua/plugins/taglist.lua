-- ctagsのバイナリパスを設定
vim.g.taglist_ctags_bin = "/opt/homebrew/bin/ctags"

-- Taglistの設定
vim.g.Tlist_Use_Right_Window = 1
vim.g.Tlist_Exit_OnlyWindow = 1
vim.g.Tlist_Show_One_File = 1
-- アルファベット順にソート
vim.g.Tlist_Sort_Type = "name"

-- F8キーでTlistToggleをトグル
vim.api.nvim_set_keymap('n', '<F8>', ':TlistToggle<CR>', { noremap = true, silent = true })

