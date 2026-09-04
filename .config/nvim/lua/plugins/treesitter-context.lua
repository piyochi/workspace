-- 関数名やクラス名を画面上部に固定表示する
-- ※ 旧APIの `patterns`(表示対象ノードの指定)は現行版で削除されており黙って無視される。
--    現在の有効キーは enable / multiwindow / max_lines / min_window_height /
--    line_numbers / multiline_threshold / trim_scope / zindex / mode
require'treesitter-context'.setup{
  enable = true,
  max_lines = 0,        -- 表示行数の上限。0以下で無制限
  trim_scope = 'outer', -- max_lines超過時にどちら側を捨てるか ('inner' / 'outer')
}
