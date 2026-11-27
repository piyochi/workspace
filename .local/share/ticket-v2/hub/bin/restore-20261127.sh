#!/bin/zsh
# 2026-11-27 の組み替え（1環境1組・環境5・6追加）の後に、12枠を復旧する。tmuxp を読み込み直した後に hub が1回だけ実行する。
#  1. Claude の会話の記録を、新しい枠の環境のフォルダへ移す（--resume は今いるフォルダの記録しか探さない）
#  2. 奇数枠で Claude を --resume で、偶数枠で Codex を起動する
# 枠と会話: [1]env1 #14747 / [3]env2 #15040 / [5]env3 #14921 / [7]env4 #15043 / [9]env5 #15047 / [11]env6 空き
set -u
P=~/.claude/projects
mvs() {  # mvs <会話ID> <元のフォルダ名> <先のフォルダ名>
  local id=$1 from=$P/$2 to=$P/$3
  mkdir -p $to
  if [[ -f $to/$id.jsonl ]]; then echo "済み: $id → $3"; return; fi
  if [[ ! -f $from/$id.jsonl ]]; then echo "⚠️ 見つからない: $from/$id.jsonl"; return 1; fi
  mv $from/$id.jsonl $to/ && { [[ -d $from/$id ]] && mv $from/$id $to/; touch $to/$id.jsonl; echo "移動: $id $2 → $3"; }
}
mvs eaea8b60-d525-4fbb-b970-ef63aba0f792 -Users-piyoh-www-ticket-v2 -Users-piyoh-www-ticket-v2-second
mvs 5990a72f-abb1-4200-ac29-c223e44a3346 -Users-piyoh-www-ticket-v2-second -Users-piyoh-www-ticket-v2-third
mvs 321cfe84-9d37-4f14-b03d-4bf38a82e0a5 -Users-piyoh-www-ticket-v2-second -Users-piyoh-www-ticket-v2-fourth
mvs 48d20218-3d88-4a88-9be9-55228e8711bb -Users-piyoh-www-ticket-v2-third -Users-piyoh-www-ticket-v2-fifth
# [11] env6 は空き（2026-11-27 ユーザー「11:14926 は間違いなのでクリアして」）。会話は移さず新しい会話で起動する

typeset -A DIR SES
DIR=(1 ~/www/ticket_v2 3 ~/www/ticket_v2_second 5 ~/www/ticket_v2_third 7 ~/www/ticket_v2_fourth 9 ~/www/ticket_v2_fifth 11 ~/www/ticket_v2_sixth)
SES=(1 4e4a0723-2f6c-4791-b5e6-40ff3bb75dbd 3 eaea8b60-d525-4fbb-b970-ef63aba0f792 5 5990a72f-abb1-4200-ac29-c223e44a3346
     7 321cfe84-9d37-4f14-b03d-4bf38a82e0a5 9 48d20218-3d88-4a88-9be9-55228e8711bb)
pane() { python3 -B -c "
import sys;sys.path.insert(0,'$HOME/.local/share/ticket-v2/hub/bin');import hub_redmine as hr
print(next(s['pane'] for s in hr.dash_get('/api/panes')['slots'] if s['slot']==$1))"; }
for n in 1 3 5 7 9 11; do
  p=$(pane $n) || { echo "⚠️ [$n] の枠が見つからない"; continue; }
  if [[ -n "${SES[$n]:-}" ]]; then rs="--resume ${SES[$n]}"; else rs=""; tmux set -p -t $p @ai_label "" ; fi
  tmux send-keys -t $p "cd ${DIR[$n]} && CODEX_SLOT=$((n + 1)) bin/claude ticket_v2 ticket_v2_api --permission-mode auto $rs" Enter
  c=$(pane $((n + 1))) || continue
  cx="bin/codex ticket_v2_api ticket_v2"   # Codex は新しい会話（resume --last だと、その環境で前に別のチケットの枠が使った会話が開く）
  tmux send-keys -t $c "cd ${DIR[$n]} && $cx" Enter
  echo "起動: [$n] $p ${DIR[$n]} / [$((n + 1))] $c"
done
