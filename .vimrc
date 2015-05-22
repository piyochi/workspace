set nocompatible
syntax on
filetype off

set rtp+=~/.vim/bundle/vundle/
call vundle#rc()


"Bundle 'vundle'
Bundle 'grep.vim'
"Bundle 'php.vim'
Bundle 'tpope/vim-rails'
Bundle 'tpope/vim-cucumber'
Bundle 'scrooloose/nerdtree'
Bundle 'soh335/vim-symfony'
Bundle 'tjennings/git-grep-vim'
Bundle 'vim-scripts/local_vimrc.vim'
Bundle 'mattn/benchvimrc-vim'
Bundle 'majutsushi/tagbar'
Bundle 'etaoins/vim-volt-syntax'
Bundle 'joonty/vdebug.git'
" :Ref phpmanual xxx
Bundle 'thinca/vim-ref'
" node.js
Bundle 'creationix/nvm'
" 補完
Bundle 'Shougo/neobundle.vim'
Bundle 'Shougo/vimproc.vim'
Bundle 'Shougo/neocomplete.vim'
Bundle 'violetyk/neocomplete-php.vim'

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




