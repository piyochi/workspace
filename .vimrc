set nocompatible
syntax on
filetype off

"set rtp+=~/.vim/bundle/vundle/
"call vundle#rc()

set runtimepath+=~/.vim/bundle/neobundle.vim/
call neobundle#begin(expand('~/.vim/bundle/'))

NeoBundleFetch 'Shougo/neobundle.vim'

NeoBundle 'grep.vim'
"NeoBundle 'php.vim'
"NeoBundle 'Shougo/neocomplcache'
"NeoBundle 'scrooloose/syntastic'
"NeoBundle 'tpope/vim-rails'
"NeoBundle 'tpope/vim-cucumber'
NeoBundle 'scrooloose/nerdtree'
"NeoBundle 'soh335/vim-symfony'
NeoBundle 'tjennings/git-grep-vim'
NeoBundle 'vim-scripts/local_vimrc.vim'
NeoBundle 'mattn/benchvimrc-vim'
NeoBundle 'majutsushi/tagbar'
NeoBundle 'etaoins/vim-volt-syntax'
NeoBundle 'joonty/vdebug.git'
" :Ref phpmanual xxx
NeoBundle 'thinca/vim-ref'
" node.js
NeoBundle 'creationix/nvm'
" 補完
NeoBundle 'Shougo/vimproc.vim'
NeoBundle 'Shougo/neocomplete.vim'
NeoBundle 'violetyk/neocomplete-php.vim'
" tmux
NeoBundle 'tpope/vim-obsession'

NeoBundle 'junegunn/vim-easy-align'


call neobundle#end()


filetype plugin indent on

"let g:pdv_template_dir = $HOME ."/.vim/bundle/pdv/templates_snip"
"nnoremap <buffer> <C-p> :call pdv#DocumentWithSnip()<CR>

" ref
let g:ref_phpmanual_path = $HOME . "/.vim/ref/php-chunked-xhtml"

set ai
set sw=4
set list
set nu
set showmode
set expandtab
set ts=4
set encoding=utf8
set fileencodings=utf8,iso-2022-jp,sjis,euc-jp
set backspace=indent,eol,start
set autoindent

let php_sql_query=1
let php_htmlInStrings=1
let g:sql_type_default='mysql'

" 補完
let g:neocomplete#enable_at_startup               = 1
let g:neocomplete#auto_completion_start_length    = 3
let g:neocomplete#enable_ignore_case              = 1
let g:neocomplete#enable_smart_case               = 1
let g:neocomplete#enable_camel_case               = 1
let g:neocomplete#use_vimproc                     = 1
let g:neocomplete#sources#buffer#cache_limit_size = 1000000
let g:neocomplete#sources#tags#cache_limit_size   = 30000000
let g:neocomplete#enable_fuzzy_completion         = 1
let g:neocomplete#lock_buffer_name_pattern        = '\*ku\*'
let g:neocomplete_php_locale                      = 'ja'

nmap <silent> ,, [mv%=<CR>
"au! BufNewFile,BufRead *.volt set filetype=htmldjango

"nerdtree
" C-e open close
nmap <silent> <C-e>      :NERDTreeToggle<CR>
vmap <silent> <C-e> <Esc>:NERDTreeToggle<CR>
omap <silent> <C-e>      :NERDTreeToggle<CR>
imap <silent> <C-e> <Esc>:NERDTreeToggle<CR>
cmap <silent> <C-e> <C-u>:NERDTreeToggle<CR>

" tagbar
nmap <F8> :TagbarToggle<CR>

" first open
autocmd vimenter * if !argc() | NERDTree | endif

autocmd bufenter * if (winnr("$") == 1 && exists("b:NERDTreeType") && b:NERDTreeType == "primary") | q | endif
let g:NERDTreeShowHidden=1
let g:NERDTreeShowBookmarks=1
let g:NERDTreeDirArrows=0

let g:NERDTreeIgnore=['\.clean$', '\.swp$', '\.bak$', '\~$']

" ステータスバーに文字コードと改行コード表示
set statusline=%<%f\ %m%r%h%w%{'['.(&fenc!=''?&fenc:&enc).']['.&ff.']'}%=%l,%c%V%8P

" Start interactive EasyAlign in visual mode (e.g. vip<Enter>)
vmap <Enter> <Plug>(EasyAlign)
" Start interactive EasyAlign for a motion/text object (e.g. gaip)
nmap ga <Plug>(EasyAlign)

" 辞書
"webdictサイトの設定
let g:ref_source_webdict_sites = {
\   'je': {
\     'url': 'http://dictionary.infoseek.ne.jp/jeword/%s',
\   },
\   'ej': {
\     'url': 'http://dictionary.infoseek.ne.jp/ejword/%s',
\   },
\   'wiki': {
\     'url': 'http://ja.wikipedia.org/wiki/%s',
\   },
\ }

"デフォルトサイト
let g:ref_source_webdict_sites.default = 'ej'

"出力に対するフィルタ。最初の数行を削除
function! g:ref_source_webdict_sites.je.filter(output)
  return join(split(a:output, "\n")[15 :], "\n")
endfunction
function! g:ref_source_webdict_sites.ej.filter(output)
  return join(split(a:output, "\n")[15 :], "\n")
endfunction
function! g:ref_source_webdict_sites.wiki.filter(output)
  return join(split(a:output, "\n")[17 :], "\n")
endfunction

nmap <Leader>rj :<C-u>Ref webdict je<Space>
nmap <Leader>re :<C-u>Ref webdict ej<Space>



