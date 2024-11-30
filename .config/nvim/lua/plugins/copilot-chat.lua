-- Copilot Chat のキーマッピング
-- Copilotチャット画面を新しくする
vim.api.nvim_set_keymap("n", "<Leader>ca", ":CopilotChatReset<CR>", { noremap = true, silent = true })
-- Copilotチャット画面の表示/非表示を切り替える
vim.api.nvim_set_keymap("n", "<Leader>cg", ":CopilotChatToggle<CR>", { noremap = true, silent = true })

require("CopilotChat").setup({
    show_help = "yes",
    prompts = {
        Explain = {
            prompt = "/COPILOT_EXPLAIN コードを日本語で説明してください",
            mapping = '<leader>ce',
            description = "コードの説明をお願いする",
        },
        Review = {
            prompt = '/COPILOT_REVIEW コードを日本語でレビューしてください。',
            mapping = '<leader>cr',
            description = "コードのレビューをお願いする",
        },
        Fix = {
            prompt = "/COPILOT_FIX このコードには問題があります。バグを修正したコードを表示してください。説明は日本語でお願いします。",
            mapping = '<leader>cf',
            description = "コードの修正をお願いする",
        },
        Optimize = {
            prompt = "/COPILOT_REFACTOR 選択したコードを最適化し、パフォーマンスと可読性を向上させてください。説明は日本語でお願いします。",
            mapping = '<leader>co',
            description = "コードの最適化をお願いする",
        },
        Docs = {
            prompt = "/COPILOT_GENERATE 選択したコードに関するドキュメントコメントを日本語で生成してください。",
            mapping = '<leader>cd',
            description = "コードのドキュメント作成をお願いする",
        },
        Tests = {
            prompt = "/COPILOT_TESTS 選択したコードの詳細なユニットテストを書いてください。説明は日本語でお願いします。describeは関数名・メソッド名でそれ以外のitやcontextなどは日本語でお願いします。",
            mapping = '<leader>ct',
            description = "テストコード作成をお願いする",
        },
        GitDiffTests = {
            prompt = "/COPILOT_TESTS 選択したgitの差分からファイル毎に詳細な変更分のユニットテストを書いてください。説明は日本語でお願いします。describeは関数名・メソッド名でそれ以外のitやcontextなどは日本語でお願いします。",
            mapping = '<leader>cy',
            description = "Git差分からテストコード作成をお願いする",
        },
        FixDiagnostic = {
            prompt = 'コードの診断結果に従って問題を修正してください。修正内容の説明は日本語でお願いします。',
            mapping = '<leader>cd',
            description = "コードの修正をお願いする",
            selection = require('CopilotChat.select').diagnostics,
        },
        Commit = {
            prompt =
            '実装差分に対するコミットメッセージを日本語で記述してください。',
            mapping = '<leader>cco',
            description = "コミットメッセージの作成をお願いする",
            selection = require('CopilotChat.select').gitdiff,
        },
        CommitStaged = {
            prompt =
            'ステージ済みの変更に対するコミットメッセージを日本語で記述してください。',
            mapping = '<leader>cs',
            description = "ステージ済みのコミットメッセージの作成をお願いする",
            selection = function(source)
                return require('CopilotChat.select').gitdiff(source, true)
            end,
        },
    },
})

