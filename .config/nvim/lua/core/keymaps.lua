-- Tab で補完メニュー進む
-- 普通のtabが効かなくなるのでS-Tabのみにした 矢印キーで補完メニューを操作する
vim.api.nvim_set_keymap('i', '<S-Tab>', [[pumvisible() ? '<C-n>' : ddc#map#manual_complete()]], {expr = true, noremap = true})
-- Shift + Tab で補完メニュー戻る
--vim.api.nvim_set_keymap('i', '<S-Tab>', [[pumvisible() ? '<C-p>' : '<C-h>']], {expr = true, noremap = true})

-- EasyAlign をビジュアルモードで起動
vim.api.nvim_set_keymap('v', '<CR>', '<Plug>(EasyAlign)', { noremap = false, silent = true })
-- EasyAlign をノーマルモードでモーションやテキストオブジェクトに対して起動
vim.api.nvim_set_keymap('n', 'ga', '<Plug>(EasyAlign)', { noremap = false, silent = true })

-- 検索時の背景色ON/OFFをF5で切替
vim.api.nvim_set_keymap('n', '<F5>', ':set hlsearch!<CR>', { noremap = true, silent = true })

-- [Tag] を <Leader>t とする
vim.api.nvim_set_keymap("n", "<Leader>t", "<Nop>", { noremap = true, silent = true })
-- タブのジャンプ t1-t9で各タブに移動
for n = 1, 9 do
  vim.api.nvim_set_keymap("n", "<Leader>t" .. n, ":tabnext " .. n .. "<CR>", { noremap = true, silent = true })
end
-- tc: 新しいタブを一番右に作る
vim.api.nvim_set_keymap("n", "tc", ":tablast | tabnew<CR>", { noremap = true, silent = true })
-- tx: タブを閉じる
vim.api.nvim_set_keymap("n", "tx", ":tabclose<CR>", { noremap = true, silent = true })
-- tn: 次のタブ
vim.api.nvim_set_keymap("n", "tn", ":tabnext<CR>", { noremap = true, silent = true })
-- tp: 前のタブ
vim.api.nvim_set_keymap("n", "tp", ":tabprevious<CR>", { noremap = true, silent = true })

-- ctrl + j or k 縦移動 現在位置から縦に次の文字がある場所へ移動する
-- ノーマルモードでのキーマッピング
vim.api.nvim_set_keymap('n', '<C-j>', '<Plug>(edgemotion-j)', { noremap = true, silent = true })
vim.api.nvim_set_keymap('n', '<C-k>', '<Plug>(edgemotion-k)', { noremap = true, silent = true })
-- ビジュアルモードでのキーマッピング
vim.api.nvim_set_keymap('v', '<C-j>', '<Plug>(edgemotion-j)', { noremap = true, silent = true })
vim.api.nvim_set_keymap('v', '<C-k>', '<Plug>(edgemotion-k)', { noremap = true, silent = true })

-- \lfでeslint,prettierの自動修正を実行
vim.api.nvim_set_keymap(
  "n",
  "<leader>lf",
  "<cmd>lua vim.lsp.buf.format()<CR>",
  { noremap = true, silent = true }
)
-- \ltでnone-lsのエラー表示を切り替える
vim.api.nvim_set_keymap(
  "n",
  "<leader>lt",
  "<cmd>lua require('utils.functions').toggle_diagnostics()<CR>",
  { noremap = true, silent = true }
)
-- \leでカーソル位置のeslinst,prettierエラーをその場に表示
vim.api.nvim_set_keymap(
  "n",
  "<leader>le",
  "<cmd>lua vim.diagnostic.open_float()<CR>",
  { noremap = true, silent = true }
)
-- \ldでカーソル位置のeslinst,prettierエラーをリスト表示
vim.api.nvim_set_keymap(
  "n",
  "<leader>ld",
  "<cmd>lua vim.diagnostic.setloclist()<CR>",
  { noremap = true, silent = true }
)

