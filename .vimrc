set nocompatible
syntax on
filetype off

set rtp+=~/.vim/bundle/vundle/
call vundle#rc()

Bundle 'vundle'
Bundle 'grep.vim'
Bundle 'php.vim'
Bundle 'Shougo/neocomplcache'
Bundle 'scrooloose/syntastic'
Bundle 'tpope/vim-rails'
Bundle 'scrooloose/nerdtree'
Bundle 'soh335/vim-symfony'
Bundle 'tjennings/git-grep-vim'

filetype plugin indent on

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

" first open
autocmd vimenter * if !argc() | NERDTree | endif

autocmd bufenter * if (winnr("$") == 1 && exists("b:NERDTreeType") && b:NERDTreeType == "primary") | q | endif
let g:NERDTreeShowHidden=1
let g:NERDTreeShowBookmarks=1
let g:NERDTreeDirArrows=0

let g:NERDTreeIgnore=['\.clean$', '\.swp$', '\.bak$', '\~$']

" $BJ8K!%A%'%C%/(B
let g:syntastic_enable_signs=1
let g:syntastic_auto_loc_list=2

" $BJd40(B
let g:neocomplcache_enable_at_startup = 1

"$B%]%C%W%"%C%W%a%K%e!<$GI=<($5$l$k8uJd$N?t!#=i4|CM$O(B100
"let g:neocomplcache_max_list = 20
""$B<+F0Jd40$r9T$&F~NO?t$r@_Dj!#=i4|CM$O(B2
let g:neocomplcache_auto_completion_start_length = 2
"$B<jF0Jd40;~$KJd40$r9T$&F~NO?t$r@)8f!#CM$r>.$5$/$9$k$HJ8;z$N:o=|;~$K=E$/$J$k(B
"let g:neocomplcache_manual_completion_start_length = 3
""$B%P%C%U%!$d<-=q%U%!%$%kCf$G!"Jd40$NBP>]$H$J$k%-!<%o!<%I$N:G>.D9$5!#=i4|CM$O(B4$B!#(B
let g:neocomplcache_min_keyword_length = 4
"$B%7%s%?%C%/%9%U%!%$%kCf$G!"Jd40$NBP>]$H$J$k%-!<%o!<%I$N:G>.D9$5!#=i4|CM$O(B4$B!#(B
"let g:neocomplcache_min_syntax_length = 4
""1:$BJd408uJd8!:w;~$KBgJ8;z!&>.J8;z$rL5;k$9$k(B
let g:neocomplcache_enable_ignore_case = 1
"$B%"%s%@!<%P!<$r6h@Z$j$H$7$?$"$$$^$$8!:w$r9T$&$+$I$&$+!#(B
"m_s$B$HF~NO$9$k$H(Bm*_s$B$H2r<a$5$l!"(Bmb_substr$BEy$K%^%C%A$9$k!#(B
let g:neocomplcache_enable_underbar_completion = 1
