"setlocal noexpandtab
setlocal list
"set tabstop=4
setlocal listchars=tab:>-

function! s:matchcursor(pat)
  let line = getline(".")
  let lastend = 0
  while lastend >= 0
    let beg = match(line,'\C'.a:pat,lastend)
    let end = matchend(line,'\C'.a:pat,lastend)
    exec "echo 'beg:". beg .", end:". end .", my: ". col(".") ."'"
    if beg < col(".") && end >= col(".")
      return matchstr(line,'\C'.a:pat,lastend)
    endif
    let lastend = end
  endwhile
  return ""
endfunction

function! s:findit(pat,repl)
  let res = s:matchcursor(a:pat)
  if res != ""
    return substitute(res,'\C'.a:pat,a:repl,'')
  else
    return ""
  endif
endfunction

if !exists('*s:checkfileread')
    function! s:checkfileread(path)
        if glob(a:path) == ""
            exec "echo 'no file name: ". a:path ."'"
            exec "edit ". a:path
        else
            exec "edit ". a:path 
        end
    endfunction
endif

" 文字列の最初の文字を大文字にする
if !exists('*s:ucfirst')
    function! s:ucfirst(str)
        return substitute(a:str, '\<.', '\u&', 'g')
    endfunction
endif

if !exists('*s:phalcon_read')
    function! s:phalcon_read(main_name, next)
        let dir_name=substitute(expand('%:p:h'), 'views', 'classes/'. a:next , 'g')
        let dir_name=substitute(dir_name, 'controllers', a:next, 'g')
        let dir_name=substitute(dir_name, 'forms', a:next, 'g')
        let dir_name=substitute(dir_name, 'models', a:next, 'g')
        let dir_name=substitute(dir_name, 'queries', a:next, 'g')
        let dir_name=substitute(dir_name, 'services', a:next, 'g')
        let dir_name=substitute(dir_name, 'validators', a:next, 'g')

        if a:main_name != ""
            let main_name = dir_name ."/". s:ucfirst(a:main_name)
        elseif expand('%:p') =~ 'views'
            let dirs = split(dir_name, "/")
            let tolower_main_name = dirs[len(dirs) - 1]
            let main_name = s:ucfirst(tolower_main_name)
            let main_name = substitute(dir_name, tolower_main_name, main_name, 'g')
        else
            let main_name=substitute(expand('%:t:r'), 'Controller', '', 'g')
            let main_name=substitute(main_name, 'Form', '', 'g')
            let main_name=dir_name."/".main_name
        end

        return main_name
    endfunction
endif


if !exists('*s:PhalconViewRead')
    function! s:PhalconViewRead (...)
        if 0 < a:0
            let volt_name = a:1.".volt"
        else
            let volt_name = ""
        end
        "let file_name=substitute(expand("%:r"), expand('%:p:h'), '', 'g')
        let main_name=substitute(expand('%:t:r'), 'Controller', '', 'g')
        let main_name=substitute(main_name, 'Form', '', 'g')
        let main_name=tolower(main_name)
        let dir_name=substitute(expand('%:p:h'), 'classes/controllers', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/forms', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/models', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/queries', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/services', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/validators', 'views', 'g')
        call s:checkfileread(dir_name."/". main_name ."/" . volt_name)
    endfunction
endif

if !exists('*s:PhalconControllerRead')
    function! s:PhalconControllerRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'controllers') . "Controller.php"
        call s:checkfileread(file_name)
    endfunction
endif

if !exists('*s:PhalconFormRead')
    function! s:PhalconFormRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'forms') . "Form.php"
        call s:checkfileread(file_name)
    endfunction
endif

if !exists('*s:PhalconModelRead')
    function! s:PhalconModelRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'models') . ".php"
        call s:checkfileread(file_name)
    endfunction
endif

if !exists('*s:PhalconQueryRead')
    function! s:PhalconQueryRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'queries') . ".php"
        call s:checkfileread(file_name)
    endfunction
endif

if !exists('*s:PhalconServiceRead')
    function! s:PhalconServiceRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'services') . ".php"
        call s:checkfileread(file_name)
    endfunction
endif

if !exists('*s:PhalconValidateRead')
    function! s:PhalconValidateRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'validators') . ".php"
        call s:checkfileread(file_name)
    endfunction
endif



command! -nargs=* PHv :call s:PhalconViewRead(<f-args>)
command! -nargs=* PHview :call s:PhalconViewRead(<f-args>)
command! -nargs=* PHc :call s:PhalconControllerRead(<f-args>)
command! -nargs=* PHcontroller :call s:PhalconControllerRead(<f-args>)
command! -nargs=* PHf :call s:PhalconFormRead(<f-args>)
command! -nargs=* PHform :call s:PhalconFormRead(<f-args>)
command! -nargs=* PHm :call s:PhalconModelRead(<f-args>)
command! -nargs=* PHmodel :call s:PhalconModelRead(<f-args>)
command! -nargs=* PHq :call s:PhalconQueryRead(<f-args>)
command! -nargs=* PHquery :call s:PhalconQueryRead(<f-args>)
command! -nargs=* PHs :call s:PhalconServiceRead(<f-args>)
command! -nargs=* PHservice :call s:PhalconServiceRead(<f-args>)
command! -nargs=* PHv :call s:PhalconValidateRead(<f-args>)
command! -nargs=* PHvalidate :call s:PhalconValidateRead(<f-args>)









