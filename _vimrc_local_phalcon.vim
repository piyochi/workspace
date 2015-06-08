"setlocal noexpandtab
setlocal list
"set tabstop=4
setlocal listchars=tab:>-

if !exists('*s:matchcursor')
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
endif

if !exists('*s:findit')
    function! s:findit(pat,repl)
        let res = s:matchcursor(a:pat)
        if res != ""
            return substitute(res,'\C'.a:pat,a:repl,'')
        else
            return ""
        endif
    endfunction
endif

if !exists('*s:checkfileread')
    function! s:checkfileread(path)
        " 1階層上を取得
        let dir_name = join(remove( split( a:path, "/" ), len( split( getcwd(), "/" ) ), -1 ), "/")
        if glob(dir_name) == ""
            exec "echo 'no dir name: ". a:path ."'"
        elseif glob(a:path) == ""
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

" スネークケース -> キャメルケース
if !exists('*s:camelcase')
    function! s:camelcase(str)
        return substitute(a:str, '\v_(.)', '\u\1', 'g')
    endfunction
endif

" キャメルケース -> スネークケース
if !exists('*s:snakecase')
    function! s:snakecase(str)
        return substitute(a:str, '\v([A-Z])', '_\L\1', 'g')
    endfunction
endif

if !exists('*s:phalcon_read')
    function! s:phalcon_read(main_name, next, ...)
        let dir_name = get(a:, 1, expand('%:p:h'))
        let dirs = split(dir_name, "views")
        let dir_name=substitute(dir_name, 'views', 'classes/'. a:next , 'g')
        let dir_name=substitute(dir_name, 'Controllers', a:next, 'g')
        let dir_name=substitute(dir_name, 'Forms', a:next, 'g')
        let dir_name=substitute(dir_name, 'Models', a:next, 'g')
        let dir_name=substitute(dir_name, 'Queries', a:next, 'g')
        let dir_name=substitute(dir_name, 'Services', a:next, 'g')
        let dir_name=substitute(dir_name, 'Validators', a:next, 'g')
        let dir_name=substitute(dir_name, 'Validation', a:next, 'g')
        let dir_name=substitute(dir_name, 'Tasks', a:next, 'g')

        if a:main_name != ""
            let main_name = s:camelcase(a:main_name)
            let main_name = s:ucfirst(main_name)
            let main_name = dir_name ."/". main_name
        elseif expand('%:p') =~ 'views'
            "let dirs = split(dir_name, "/")
            let tolower_main_name = dirs[len(dirs) - 1]
            let main_name = s:camelcase(tolower_main_name)
            let main_name = s:ucfirst(main_name)
            let main_name = substitute(dir_name, tolower_main_name, main_name, 'g')
        else
            let main_name=substitute(expand('%:t:r'), 'Controller', '', 'g')
            let main_name=substitute(main_name, 'Form', '', 'g')
            let main_name=substitute(main_name, 'Task', '', 'g')
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
        let main_name=substitute(main_name, 'Task', '', 'g')
        let main_name=s:snakecase(main_name)
        let dir_name=substitute(expand('%:p:h'), 'classes/Controllers', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/Forms', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/Models', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/Queries', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/Services', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/Validators', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/Validation', 'views', 'g')
        let dir_name=substitute(dir_name, 'classes/Tasks', 'views', 'g')
        let dirs = split(dir_name, "views/")
        let prev_dir_name = dirs[len(dirs) - 1]
        let next_dir_name = s:snakecase(prev_dir_name)
        let dir_name = substitute(dir_name, prev_dir_name, next_dir_name, 'g')
        let name = dir_name."/". main_name ."/" . volt_name
        let name = substitute(name, '/_', '/', 'g')
        call s:checkfileread(name)
    endfunction
endif

if !exists('*s:PhalconControllerRead')
    function! s:PhalconControllerRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'Controllers') . "Controller.php"
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

        let file_name = s:phalcon_read(main_name, 'Forms') . "Form.php"
        call s:checkfileread(file_name)
    endfunction
endif

if !exists('*s:PhalconTaskRead')
    function! s:PhalconTaskRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'Tasks') . "Task.php"
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

        let file_name = s:phalcon_read(main_name, 'Models') . ".php"
        if glob(file_name) == ""
            let dir_name = expand('%:p:h') . "/../../../../classes/Models"
            let file_name_parent = s:phalcon_read(main_name, 'Models', dir_name) . ".php"
            if glob(file_name_parent) != ""
                let file_name = file_name_parent
            end
        end
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

        let file_name = s:phalcon_read(main_name, 'Queries') . ".php"
        if glob(file_name) == ""
            let dir_name = expand('%:p:h') . "/../../../../classes/Queries"
            let file_name_parent = s:phalcon_read(main_name, 'Queries', dir_name) . ".php"
            if glob(file_name_parent) != ""
                let file_name = file_name_parent
            end
        end
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

        let file_name = s:phalcon_read(main_name, 'Services') . ".php"
        if glob(file_name) == ""
            let dir_name = expand('%:p:h') . "/../../../../classes/Services"
            let file_name_parent = s:phalcon_read(main_name, 'Services', dir_name) . ".php"
            if glob(file_name_parent) != ""
                let file_name = file_name_parent
            end
        end
        call s:checkfileread(file_name)
    endfunction
endif

if !exists('*s:PhalconValidatorsRead')
    function! s:PhalconValidatorsRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'Validators') . ".php"
        if glob(file_name) == ""
            let dir_name = expand('%:p:h') . "/../../../../classes/Validators"
            let file_name_parent = s:phalcon_read(main_name, 'Validators', dir_name) . ".php"
            if glob(file_name_parent) != ""
                let file_name = file_name_parent
            end
        end
        call s:checkfileread(file_name)
    endfunction
endif

if !exists('*s:PhalconValidationRead')
    function! s:PhalconValidationRead (...)
        if 0 < a:0
            let main_name = a:1 
        else
            let main_name = ""
        end

        let file_name = s:phalcon_read(main_name, 'Validation') . ".php"
        if glob(file_name) == ""
            let dir_name = expand('%:p:h') . "/../../../../classes/Validation"
            let file_name_parent = s:phalcon_read(main_name, 'Validation', dir_name) . ".php"
            if glob(file_name_parent) != ""
                let file_name = file_name_parent
            end
        end
        call s:checkfileread(file_name)
    endfunction
endif




command! -nargs=* PHt :call s:PhalconViewRead(<f-args>)
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
command! -nargs=* PHvs :call s:PhalconValidatorsRead(<f-args>)
command! -nargs=* PHvn :call s:PhalconValidationRead(<f-args>)
command! -nargs=* PHta :call s:PhalconTaskRead(<f-args>)
command! -nargs=* PHtask :call s:PhalconTaskRead(<f-args>)





