-- gcc でコメントと解除を切り替え
-- JavaScript, TypeScript, React, TSX, CJS などのコメント形式をカスタマイズ
vim.api.nvim_create_autocmd("BufReadPost", {
    pattern = { "*.js", "*.jsx", "*.ts", "*.tsx", "*.cjs", "*.mjs" },
    callback = function()
      vim.cmd("let b:tcommentary_format = '//\\ '")
    end,
})

