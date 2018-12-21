
#compdef tmuxp

_tmuxp() {
  local -a cmds projects

  if (( CURRENT == 2 )); then
    cmds=(
      'convert:Convert a tmuxp config between JSON and YAML.'
      'freeze:Snapshot a session into a config.'
      'import:Import a teamocil/tmuxinator config.'
      'load:Load tmuxp workspaces.'
    )
    _describe -t commands "subcommand" cmds
  elif (( CURRENT == 3 )); then
    case $words[2] in
      import)
        cmds=(
          'teamocil:Convert and import a teamocil config.'
          'tmuxinator:Convert and import a tmuxinator config.'
        )
        _describe -t commands "subcommand" cmds
        ;;

      load)
        projects=(`find ~/.tmuxp/ -name \*.yaml | cut -d/ -f5 | sed s:.yaml::g`)
        _arguments '*:projects:($projects)'
        ;;

      *)
        _files
        ;;
    esac
  elif (( CURRENT == 4 )); then
    case $words[3] in
      tmuxinator)
        projects=(`find ~/.tmuxinator/ -name \*.yml`)
        _arguments '*:projects:($projects)'
        ;;
      *)
        _files
        ;;
    esac
  fi

  return 0;
}

compdef _tmuxp tmuxp

# Local Variables:
# mode: Shell-Script
# sh-indentation: 2
# indent-tabs-mode: nil
# sh-basic-offset: 2
# End:
# vim: ft=zsh sw=2 ts=2 et
