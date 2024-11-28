-- 補完
vim.g['denops#deno'] = vim.fn.expand('~/.deno/bin/deno')
vim.fn['ddc#custom#patch_global']('ui', 'native')
vim.fn['ddc#custom#patch_global']('sources', {'around', 'file'})
vim.fn['ddc#custom#patch_global']('sourceOptions', {
  _ = {
    matchers = {'matcher_head'},
    sorters = {'sorter_rank'}
  },
  around = {
    mark = 'A'
  },
  file = {
    mark = 'F',
    isVolatile = true,
    forceCompletionPattern = '\\S/\\S*'
  }
})
vim.fn['ddc#enable']()
