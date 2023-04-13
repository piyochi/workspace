HISTFILE=$HOME/.zsh-history           # 履歴をファイルに保存する
HISTSIZE=100000                       # メモリ内の履歴の数
SAVEHIST=100000                       # 保存される履歴の数
setopt extended_history               # 履歴ファイルに時刻を記録
function history-all { history -E 1 } # 全履歴の一覧を出力する


# Path to your oh-my-zsh installation.
  export ZSH=/home/ubuntu/.oh-my-zsh

# Set name of the theme to load.
# Look in ~/.oh-my-zsh/themes/
# Optionally, if you set this to "random", it'll load a random theme each
# time that oh-my-zsh is loaded.
ZSH_THEME="crunch"

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion. Case
# sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment the following line to disable bi-weekly auto-update checks.
# DISABLE_AUTO_UPDATE="true"

# Uncomment the following line to change how often to auto-update (in days).
# export UPDATE_ZSH_DAYS=13

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# The optional three formats: "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# HIST_STAMPS="mm/dd/yyyy"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder

# Which plugins would you like to load? (plugins can be found in ~/.oh-my-zsh/plugins/*)
# Custom plugins may be added to ~/.oh-my-zsh/custom/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
#plugins=(git rails ruby gem tmuxinator)
plugins=(git rails ruby gem)

# User configuration

export PATH="$HOME/.linuxbrew/Library/Homebrew/shims/linux/super:$HOME/.linuxbrew/opt/zstd/bin:$HOME/.linuxbrew/opt/binutils/bin:$PATH"
export PATH="$HOME/.linuxbrew/bin:$PATH"
export PATH="$HOME/.linuxbrew/sbin:$PATH"
export PATH=$HOME/.rbenv/shims:$HOME/.rbenv/bin:/usr/local/bin:/bin:/usr/bin:/home/ubuntu/bin:/usr/local/sbin:/usr/sbin:/sbin:$HOME/.config/composer/vendor/bin:$PATH
#  export PATH="/usr/local/bin:/bin:/usr/bin:/home/ubuntu/bin:/usr/local/sbin:/usr/sbin:/sbin:/home/ubuntu/.rbenv/shims:/home/ubuntu/.rbenv/bin:/usr/local/bin:/bin:/usr/bin:/home/ubuntu/bin:/usr/local/sbin:/usr/sbin:/sbin:/home/ubuntu/.rbenv/versions/2.0.0-p247/bin/"
# export MANPATH="/usr/local/man:$MANPATH"

source $ZSH/oh-my-zsh.sh

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Preferred editor for local and remote sessions
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='mvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch x86_64"

# ssh
# export SSH_KEY_PATH="~/.ssh/dsa_id"

# Set personal aliases, overriding those provided by oh-my-zsh libs,
# plugins, and themes. Aliases can be placed here, though oh-my-zsh
# users are encouraged to define aliases within the ZSH_CUSTOM folder.
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"

LANG=ja_JP.UTF-8
LC_CTYPE=ja_JP.UTF-8

eval "$(rbenv init - zsh)"

export EDITOR='vim'
export GIT_EDITOR='vim'
export SHELL='zsh'

# tmux のwindowタイトルを固定
export DISABLE_AUTO_TITLE=true
# tmuxp 補完
source ~/.tmuxp/tmuxp.zsh

autoload -U compinit
compinit

function git_diff_archive()
{
  local diff=""
  local h="HEAD"
  if [ $# -eq 1 ]; then
    if expr "$1" : '[0-9]*$' > /dev/null ; then
      diff="HEAD~${1} HEAD"
    else
      diff="${1} HEAD"
    fi
  elif [ $# -eq 2 ]; then
    diff="${2} ${1}"
    h=$1
  fi
  if [ "$diff" != "" ]; then
    diff="git diff --diff-filter=d --name-only ${diff}"
  fi
  git archive --format=zip --prefix=root/ $h `eval $diff` -o archive.zip
}

export GOPATH="$HOME/go"
export PATH="/opt/local/bin:/opt/local/sbin:$PATH:$GOPATH/bin"

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

export VTE_CJK_WIDTH=1

[[ -s "$HOME/.avn/bin/avn.sh" ]] && source "$HOME/.avn/bin/avn.sh" # load avn

export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
if command -v pyenv 1>/dev/null 2>&1; then
  eval "$(pyenv init -)"
fi
eval "$(pyenv virtualenv-init -)"

export PATH="/home/ubuntu/.local/bin:$PATH"

export PATH="./bin:$PATH"

export PATH="$HOME/.rbenv/versions/2.0.0-p451/bin:$PATH"
eval "$(rbenv init -)"

# branchを比較しての変更コミット一覧
# git_diff_commit [master..release] or [master..]
alias git_diff_commit='git log --no-merges --oneline'
alias git_diff_user='git log --no-merges --format="%h %<(15,trunc)%an %s"'
# branchを比較しての変更ファイル一覧
# git_diff_file [master..release] or [master]
alias git_diff_file='git diff --name-only'

# マージ済のブランチを一括削除（master/release/developは省く）
alias git_delete_merged_branch="git branch --merged|egrep -v '\*|develop|master|release'|xargs git branch -d"


# fzf
# git clone https://github.com/junegunn/fzf.git
# ./fzf/install
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh
export FZF_DEFAULT_OPTS='--preview "bat --style=numbers --color=always {} | head -500"'
# ファイル検索してそのままvimを開く
fvim() {
  files=$(git ls-files) &&
    selected_files=$(echo "$files" | fzf -m --preview 'head -100 {}') &&
    vim $selected_files
}
# ファイル検索してそのままgit add する
fga() {
  modified_files=$(git status --short | awk '{print $2}') &&
    selected_files=$(echo "$modified_files" | fzf -m --preview 'git diff --color=always {}') &&
    git add $selected_files
}
# fbr - checkout git branch
fbl() {
  local branches branch
  branches=$(git branch -vv) &&
  branch=$(echo "$branches" | fzf +m) &&
  git checkout $(echo "$branch" | awk '{print $1}' | sed "s/.* //")
}
# fbr - checkout git branch (including remote branches)
fbr() {
  local branches branch
  branches=$(git branch --all | grep -v HEAD) &&
  branch=$(echo "$branches" |
           fzf-tmux -d $(( 2 + $(wc -l <<< "$branches") )) +m) &&
  git checkout $(echo "$branch" | sed "s/.* //" | sed "s#remotes/[^/]*/##")
}
# fd - cd to selected directory
fd() {
  local dir
  dir=$(find ${1:-.} -path '*/\.*' -prune \
                  -o -type d -print 2> /dev/null | fzf +m) &&
  cd "$dir"
}

# github command gh
eval "$(gh completion -s zsh)"

# pdftk-java
# cd ~/.local/bin/
# wget https://gitlab.com/pdftk-java/pdftk/-/jobs/1527259628/artifacts/raw/build/libs/pdftk-all.jar
# chmod 0755 pdftk-all.jar
# alias pdftk="java -jar $HOME/.local/bin/pdftk-all.jar"

