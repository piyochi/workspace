set nocompatible
syntax on
filetype off

set rtp+=~/.vim/bundle/vundle/
call vundle#rc()

Bundle 'vundle'
Bundle 'grep.vim'
"Bundle 'php.vim'
"Bundle 'Shougo/neocomplcache'
"Bundle 'scrooloose/syntastic'
Bundle 'tpope/vim-rails'
Bundle 'tpope/vim-cucumber'
Bundle 'scrooloose/nerdtree'
Bundle 'soh335/vim-symfony'
Bundle 'tjennings/git-grep-vim'
Bundle 'vim-scripts/local_vimrc.vim'
Bundle 'mattn/benchvimrc-vim'
Bundle 'majutsushi/tagbar'

filetype plugin indent on

let g:pdv_template_dir = $HOME ."/.vim/bundle/pdv/templates_snip"
nnoremap <buffer> <C-p> :call pdv#DocumentWithSnip()<CR>

set ai
set sw=2
set list
set nu
set showmode
set expandtab
set ts=2
set encoding=utf8
set fileencodings=utf8,iso-2022-jp,sjis,euc-jp

nmap <silent> ,, [mv%=<CR>

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


" 文法チェック
"let g:syntastic_enable_signs=1
"let g:syntastic_auto_loc_list=2

" 補完
"let g:neocomplcache_enable_at_startup = 1

"ポップアップメニューで表示される候補の数。初期値は100
"let g:neocomplcache_max_list = 20
""自動補完を行う入力数を設定。初期値は2
"let g:neocomplcache_auto_completion_start_length = 2
"手動補完時に補完を行う入力数を制御。値を小さくすると文字の削除時に重くなる
"let g:neocomplcache_manual_completion_start_length = 3
""バッファや辞書ファイル中で、補完の対象となるキーワードの最小長さ。初期値は4。
"let g:neocomplcache_min_keyword_length = 4
"シンタックスファイル中で、補完の対象となるキーワードの最小長さ。初期値は4。
"let g:neocomplcache_min_syntax_length = 4
""1:補完候補検索時に大文字・小文字を無視する
"let g:neocomplcache_enable_ignore_case = 1
"アンダーバーを区切りとしたあいまい検索を行うかどうか。
"m_sと入力するとm*_sと解釈され、mb_substr等にマッチする。
"let g:neocomplcache_enable_underbar_completion = 1
