set nocompatible
syntax on
filetype off

" vim-plug install
" curl -fLo ~/.vim/autoload/plug.vim --create-dirs https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
call plug#begin('~/.vim/plugged')

" vim 非同期処理
Plug 'Shougo/vimproc'

Plug 'Shougo/unite.vim'

" :Grep 検索
Plug 'vim-scripts/grep.vim'
Plug 'vim-scripts/php.vim'
Plug 'scrooloose/syntastic'
Plug 'tpope/vim-rails'
Plug 'scrooloose/nerdtree'
Plug 'tjennings/git-grep-vim'
Plug 'vim-scripts/local_vimrc.vim'
Plug 'mattn/benchvimrc-vim'
Plug 'majutsushi/tagbar'
" PHPのXdebugをvim上で管理できるやつ現状動かないのでPHPやるときに要調査
"Plug 'joonty/vdebug.git'
" :Ref phpmanual xxx
Plug 'thinca/vim-ref'
" node.js
Plug 'creationix/nvm'
" 補完
Plug 'Shougo/vimproc.vim'
Plug 'Shougo/neocomplete.vim'

" tmux
Plug 'tpope/vim-obsession'

Plug 'junegunn/vim-easy-align'
Plug 'xwsoul/vim-zephir'

Plug 'violetyk/cake.vim'

" node.js
" gfでrequire先に移動、ctrl+^で戻れる
Plug 'moll/vim-node'
" js indent
Plug 'pangloss/vim-javascript'
" js syntax
Plug 'jelera/vim-javascript-syntax'

Plug 'othree/html5.vim'

" javascript整形 prettier用
Plug 'prettier/vim-prettier'
" javascriptソースチェック eslint
" install不可になっているので要調査
"Plug 'vim-syntastic/syntastic.git'

Plug 'vim-scripts/taglist.vim'

Plug 'othree/html5.vim'

" python
"Plug 'davidhalter/jedi-vim'
" cd ~/.vim/plugin/jedi-vim/
" git submodule update --init

" python文法チェック
Plug 'andviro/flake8-vim'

" インデントを可視化
Plug 'Yggdroot/indentLine'

Plug 'basyura/unite-rails'

" .vue色付
Plug 'posva/vim-vue'

" ruby 一括コメント Ctrl + -
Plug 'tomtom/tcomment_vim'

" vim ctags サポート
Plug 'wesleyche/SrcExpl'

call plug#end()


filetype plugin indent on

"let g:pdv_template_dir = $HOME ."/.vim/bundle/pdv/templates_snip"
"nnoremap <buffer> <C-p> :call pdv#DocumentWithSnip()<CR>

" ref
let g:ref_phpmanual_path = $HOME . "/.vim/ref/php-chunked-xhtml"

set ai
set sw=2
set list
set nu
set showmode
set expandtab
set ts=2
set encoding=utf8
set fileencodings=utf8,iso-2022-jp,sjis,euc-jp
set backspace=indent,eol,start
set autoindent
set ambiwidth=double

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
let g:neocomplete#sources#buffer#cache_limit_size = 100000
let g:neocomplete#sources#tags#cache_limit_size   = 3000000
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
"nmap <F8> :TagbarToggle<CR>

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

" Alignを日本語環境で使用するための設定
let g:Align_xstrlen = 3

" コピペ
" <space>" copy, <space>p paste
" y でコピーした後に、<space>"で保存、<space>p でペースト
noremap [MyPrefix] <Nop>
map <Space> [MyPrefix]
" クリップボードの内容を名前付きレジスタに逃がす
nnoremap [MyPrefix]" :<C-u>let @y=@0<CR>
" 名前付きレジスタからペースト
nnoremap [MyPrefix]p "yp
nnoremap [MyPrefix]P "yP

" html indent
let g:html5_event_handler_attributes_complete = 1
let g:html5_rdfa_attributes_complete = 1
let g:html5_microdata_attributes_complete = 1
let g:html5_aria_attributes_complete = 1

" javascript整形 prettier
let g:prettier#autoformat = 0
"autocmd BufWritePre *.js,*.jsx,*.mjs,*.ts,*.tsx,*.css,*.less,*.scss,*.json,*.graphql,*.md,*.vue Prettier
autocmd BufWritePre *.js,*.jsx,*.mjs,*.ts,*.tsx,*.less,*.json,*.graphql,*.vue Prettier

" javascript整形 ESLint configuration
set statusline+=%#warningmsg#
set statusline+=%{SyntasticStatuslineFlag()}
set statusline+=%*

let g:syntastic_always_populate_loc_list = 1
let g:syntastic_loc_list_height = 5
let g:syntastic_auto_loc_list = 0
let g:syntastic_check_on_open = 0
let g:syntastic_check_on_wq = 0
let g:syntastic_javascript_checkers = ['eslint']
let g:syntastic_mode_map = { 'mode': 'passive', 'active_filetypes': [],'passive_filetypes': [] } " 重いので初期は無効にする

let g:syntastic_error_symbol = 'X'
let g:syntastic_style_error_symbol = 'X'
let g:syntastic_warning_symbol = '!'
let g:syntastic_style_warning_symbol = '!'

highlight link SyntasticErrorSign SignColumn
highlight link SyntasticWarningSign SignColumn
highlight link SyntasticStyleErrorSign SignColumn
highlight link SyntasticStyleWarningSign SignColumn

" Space + c eslint チェック
nnoremap <Space>c :SyntasticCheck<CR>
" Space + s eslint 有効無効切替
nnoremap <Space>s :SyntasticToggleMode<CR>


" Powerline settings
" sudo apt install -y python-pip
" sudo apt install -y python2-pip
" pip install --user powerline-shell
set laststatus=2
set showtabline=2
set t_Co=16
set noshowmode
python3 from powerline.vim import setup as powerline_setup
python3 powerline_setup()
python3 del powerline_setup


colorscheme pablo
"colorscheme peachpuff

" 選択した領域の色を設定
highlight Visual term=reverse cterm=reverse gui=reverse guifg=Grey80 guibg=fg
" 検索時の背景色
highlight Search ctermbg=5 ctermfg=2

autocmd BufRead,BufNewFile *.ect setfiletype eruby.html

" python jedi-vim
" .入力時に補完候補を表示しない ctrl+spaceで出る
"let g:jedi#popup_on_dot = 0
" 勝手に最初の候補を入力しない
"let g:jedi#popup_select_first = 0
" docstringは表示しない
"autocmd FileType python setlocal completeopt-=preview

"autocmd BufNewFile,BufRead *.rb set syntax=rspec

" :Tlist メソッド一覧
" 右側に表示
let Tlist_Use_Right_Window = 1
" taglistのウィンドウだけならvimを閉じる
let Tlist_Exit_OnlyWindow = 1
" 現在表示中のファイルのみ対象
let Tlist_Show_One_File = 1
" どの順番でソートするか
" 未設定(定義順) or name(アルファベット順)
let Tlist_Sort_Type = "name"
" F8 で開閉
nmap <F8> :TlistToggle<CR>

" 自動表示しない :tag で表示
let g:SrcExpl_RefreshTime   = 0
" ctags 自動アップデート
let g:SrcExpl_UpdateTags = 1
" F9 で起動
nmap <F9> :SrcExplToggle<CR>
"プレビューウインドウの高さ
let g:SrcExpl_WinHeight     = 20
