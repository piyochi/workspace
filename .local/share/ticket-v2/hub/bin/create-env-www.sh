#!/bin/bash
#
# create-env.sh — 新規 env (ticket_v2_project{N}) を作って起動するところまで行う
#
# 使い方:
#   ./tools/create-env.sh <N> [--config-from envX] [--db-from envY]
#   例: ./tools/create-env.sh 4                                 # env4 を作る
#       ./tools/create-env.sh 4 --config-from env3 --db-from env2
#
#   --config-from  gitignore 済みの設定 (docker/.env / database.yml / development.yml 等) と
#                  vendor/bundle / uploads / node_modules のコピー元。既定: 既存の最大番号の env
#   --db-from      DB の dump 元。既定: --config-from と同じ。
#                  feature branch で作業中の env を選ぶと、その branch の migration が
#                  新 env に持ち込まれる。release にいる env を選ぶ
#
# 手順の正本は各 env の .claude/docs/multi-env-setup.md。ここはそれを N で機械化したもの。
# 途中で失敗しても再実行で続きから進む (終わった step は判定して飛ばす)。
#
# env 固有値の書き換えはコピー元 env の値から機械的に導く:
#   名前   ticket_v2_api_{S} → ticket_v2_api_{N} / ENV_SUFFIX=_{S} → _{N} / corichlocal{S} → corichlocal{N}
#   ポート env1 の値 + 10*(n-1) の規則で、コピー元のポートだけを +10*(N-S) ずらす
# env1 は名前に数字が付かないので、コピー元にはできない (env2 以降を使う)。
#
# /etc/hosts は sudo が要るため、root 所有の helper (tools/install-env-hosts-helper.sh で 1 回だけ導入)
# 経由でパスワード無しに追記する。未導入なら導入コマンドを表示して終わる。

set -euo pipefail

die() { echo "エラー: $*" >&2; exit 1; }
step() { echo ""; echo "▶ $*"; }

N="${1:-}"
shift || true
[[ "$N" =~ ^[0-9]+$ ]] && [ "$N" -ge 2 ] || die "使い方: $0 <N (2 以上)> [--config-from envX] [--db-from envY]"

# ~/www 版（2026-11-27 hub）: 環境のフォルダは ~/www/ticket_v2{,_second,_third,_fourth,_fifth,_sixth}
CORICH="$HOME/www"
DEVTOOLS="$HOME/www/ticket_v2_devtools"
env_dir() { local n="${1#env}"; case "$n" in 1) echo "$CORICH/ticket_v2";; 2) echo "$CORICH/ticket_v2_second";; 3) echo "$CORICH/ticket_v2_third";;
  4) echo "$CORICH/ticket_v2_fourth";; 5) echo "$CORICH/ticket_v2_fifth";; 6) echo "$CORICH/ticket_v2_sixth";; *) echo "$CORICH/ticket_v2_env$n";; esac; }

CONFIG_FROM=""
DB_FROM=""
while [ $# -gt 0 ]; do
  case "$1" in
    --config-from) CONFIG_FROM="$2"; shift 2 ;;
    --db-from) DB_FROM="$2"; shift 2 ;;
    *) die "不明な引数: $1" ;;
  esac
done
if [ -z "$CONFIG_FROM" ]; then
  # 既存の最大番号 (自分自身は除く)
  CONFIG_FROM="$(for p in "$CORICH"/ticket_v2_project[0-9]*; do
    n="${p##*ticket_v2_project}"; [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" != "$N" ] && echo "$n"
  done | sort -n | tail -1)"
  [ -n "$CONFIG_FROM" ] || die "コピー元にできる env (env2 以降) がありません"
fi
S="${CONFIG_FROM#env}"
D="${DB_FROM:-env$S}"; D="${D#env}"
[ "$S" != "1" ] && [ "$D" != "1" ] || die "env1 は名前に数字が付かないのでコピー元にできません"
[ "$S" != "$N" ] && [ "$D" != "$N" ] || die "コピー元と作成先が同じです"

SRC="$(env_dir "$S")"
NEW="$(env_dir "$N")"
[ -d "$SRC/ticket_v2_api" ] || die "コピー元がありません: $SRC"

API_P="ticket_v2_api_$N"          # compose project 名 (env1/2/3 と衝突させない)
FRONT_P="ticket_v2_api_${N}_f"   # env3・env4 と同じ名前（~/.tmuxp の app server と合わせる）
COMPOSE_API=(docker compose -p "$API_P" -f "$NEW/ticket_v2_api/docker/docker-compose.yml" --env-file "$NEW/ticket_v2_api/docker/.env")
COMPOSE_FRONT=(docker compose -p "$FRONT_P" -f "$NEW/ticket_v2/docker-compose.yml" --env-file "$NEW/ticket_v2/.env.development")

echo "🔧 env$N を作成: $NEW"
echo "   設定のコピー元 env$S / DB の dump 元 env$D"

# ------------------------------------------------------------------
step "[1/10] clone (親 repo + bin/clone.sh のサブ repo)"
if [ -d "$NEW/.git" ]; then
  echo "  済み"
else
  git clone "$(git -C "$SRC" remote get-url origin)" "$NEW"
fi
# サブ repo は ticket_v2・ticket_v2_api だけ（容量のため。env1 からローカル clone して object をハードリンクで共有し、origin を GitHub に向ける）
for r in ticket_v2 ticket_v2_api; do
  if [ -d "$NEW/$r/.git" ]; then echo "  済み: $r"; continue; fi
  git clone -q "$HOME/www/ticket_v2/$r" "$NEW/$r"
  git -C "$NEW/$r" remote set-url origin "$(git -C "$HOME/www/ticket_v2/$r" remote get-url origin)"
  git -C "$NEW/$r" fetch -q origin
  git -C "$NEW/$r" checkout -q -B release origin/release
  echo "  clone: $r (release)"
done

# ------------------------------------------------------------------
step "[2/10] gitignore 済み設定を env$S からコピーし env$N の値へ書き換え"
# ポート: env1 の値。env n では +10*(n-1)
PORT_BASES="3000 3001 3306 3307 3308 3309 3310 3311 6379 1080 1025 9324 9325 8000 4010
            5173 5174 5175 5176 5177 6173 6174 6175 6176 6177"
PORT_MAP=""
for b in $PORT_BASES; do
  PORT_MAP="$PORT_MAP $((b + 10 * (S - 1)))=$((b + 10 * (N - 1)))"
done
rewrite() {  # rewrite <file> : env$S 固有の値を env$N に書き換える
  PORT_MAP="$PORT_MAP" S="$S" N="$N" perl -pi -e '
    BEGIN { %p = map { split /=/ } split " ", $ENV{PORT_MAP}; ($s, $n) = @ENV{qw(S N)} }
    s/\b(ticket_v2_api|ticket_v2|mysql_tools|elasticmq)_$s(?![0-9])/$1_$n/g;
    s/(?<==)_$s(?![0-9])/_$n/g;
    s/corichlocal$s(?=\.)/corichlocal$n/g;
    s/\b(\d{4})\b/exists $p{$1} ? $p{$1} : $1/ge;
  ' "$1"
}
CONFIG_FILES=(
  ticket_v2_api/docker/.env
  ticket_v2_api/docker/local.env
  ticket_v2_api/docker/docker-compose.yml
  ticket_v2_api/docker/elasticmq.conf
  ticket_v2_api/config/database.yml
  ticket_v2_api/config/database.e2e.yml
  ticket_v2_api/config/database.test.yml
  ticket_v2_api/config/master.key
  ticket_v2_api/config/initializers/_smtp.rb
  ticket_v2_api/config/redis/shared.yml
  ticket_v2_api/config/settings/development.yml
  ticket_v2_api/config/settings/e2e.yml
  ticket_v2_api/.rubocop_todo.yml
  ticket_v2/.env.development
)
for f in "${CONFIG_FILES[@]}"; do
  if [ -e "$NEW/$f" ]; then
    echo "  済み: $f"
    continue
  fi
  [ -e "$SRC/$f" ] || { echo "  ⚠️ コピー元に無い: $f"; continue; }
  mkdir -p "$(dirname "$NEW/$f")"
  cp -p "$SRC/$f" "$NEW/$f"
  case "$f" in
    *master.key|*.rubocop_todo.yml) ;;  # env 固有値を持たない
    *) rewrite "$NEW/$f" ;;
  esac
  echo "  コピー: $f"
done
# 書き換え漏れの検出: コピー元 env の名前・ドメインが残っていたら止める
LEFT="$(cd "$NEW" && grep -lE "ticket_v2_api_$S([^0-9]|\$)|corichlocal$S\.|ENV_SUFFIX=_$S\b" "${CONFIG_FILES[@]}" 2>/dev/null || true)"
[ -z "$LEFT" ] || die "env$S の値が残っています: $LEFT"

# ------------------------------------------------------------------
step "[3/10] vendor/bundle / uploads / node_modules をコピー (APFS clone で容量を食わない)"
for d in ticket_v2_api/vendor ticket_v2_api/uploads ticket_v2/node_modules; do
  if [ -d "$NEW/$d" ] && [ -n "$(ls -A "$NEW/$d" 2>/dev/null)" ]; then
    echo "  済み: $d"
  elif [ -d "$SRC/$d" ]; then
    rm -rf "${NEW:?}/$d"   # 空 dir があると cp -R が二重ネストする
    cp -Rc "$SRC/$d" "$NEW/$d" 2>/dev/null || cp -R "$SRC/$d" "$NEW/$d"
    echo "  コピー: $d"
  fi
done

# ------------------------------------------------------------------
step "[4/10] DB / redis / smtp / sqs を起動 (project 名 $API_P)"
"${COMPOSE_API[@]}" up -d \
  ticket_v2_api_db ticket_v2_api_db_test \
  ticket_v2_api_promoter_db ticket_v2_api_promoter_db_test \
  ticket_v2_api_portal_db ticket_v2_api_portal_db_test \
  ticket_v2_api_redis ticket_v2_api_smtp elasticmq mysql_tools
DBS=(ticket_v2_api_${N}_db ticket_v2_api_${N}_db_test
     ticket_v2_api_${N}_promoter_db ticket_v2_api_${N}_promoter_db_test
     ticket_v2_api_${N}_portal_db ticket_v2_api_${N}_portal_db_test)
wait_mysql() {  # wait_mysql <container...>
  local c i
  for c in "$@"; do
    for i in $(seq 1 60); do
      docker exec "$c" mysql -uroot -proot -e "SELECT 1" >/dev/null 2>&1 && break
      [ "$i" = 60 ] && die "$c の MySQL が起動しません"
      sleep 2
    done
  done
}
wait_mysql "${DBS[@]}"
echo "  MySQL ready"

# ------------------------------------------------------------------
step "[5/10] env$D の DB を dump して env$N へ restore"
if docker exec "ticket_v2_api_${N}_promoter_db" mysql -uroot -proot -N \
     -e "SHOW DATABASES LIKE 'ticket\_v2\_api\_${N}\_promoter\_local\_%'" 2>/dev/null | grep -q .; then
  echo "  済み (shard DB が既にある)"
else
  # dump 元が止まっていたら DB コンテナだけ起動し、終わったら止め直す (他は触らない)
  STARTED=()
  for kind in db promoter_db portal_db; do
    c="ticket_v2_api_${D}_${kind}"
    if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" != "true" ]; then
      docker start "$c" >/dev/null && STARTED+=("$c")
    fi
  done
  wait_mysql "ticket_v2_api_${D}_db" "ticket_v2_api_${D}_promoter_db" "ticket_v2_api_${D}_portal_db"
  for kind in db promoter_db portal_db; do
    src_c="ticket_v2_api_${D}_${kind}"
    dst_c="ticket_v2_api_${N}_${kind}"
    for db in $(docker exec "$src_c" mysql -uroot -proot -N -e "SHOW DATABASES LIKE 'ticket\_v2\_api\_${D}\_%'" 2>/dev/null); do
      echo "  $db → ${db/ticket_v2_api_${D}_/ticket_v2_api_${N}_}"
      docker exec "$src_c" mysqldump -uroot -proot --single-transaction --routines --triggers \
          --add-drop-database --databases "$db" 2>/dev/null \
        | perl -pe "s/ticket_v2_api_${D}_/ticket_v2_api_${N}_/g" \
        | docker exec -i "$dst_c" mysql -uroot -proot 2>/dev/null
    done
  done
  [ ${#STARTED[@]} -eq 0 ] || docker stop "${STARTED[@]}" >/dev/null
fi

# ------------------------------------------------------------------
step "[6/10] MySQL user に env$N の全 DB への権限を付与"
# 初期 user は MYSQL_DATABASE の 1 DB にしか grant が無い。restore した shard / test shard 用
for c in "${DBS[@]}"; do
  docker exec "$c" mysql -uroot -proot -e \
    "GRANT ALL PRIVILEGES ON \`ticket\_v2\_api\_${N}\_%\`.* TO 'ticket_v2_api'@'%'; FLUSH PRIVILEGES;" 2>/dev/null
done
echo "  OK"

# ------------------------------------------------------------------
step "[7/10] Rails app を起動して migrate"
"${COMPOSE_API[@]}" up -d ticket_v2_api_app
for i in $(seq 1 90); do
  docker logs "ticket_v2_api_${N}_app" 2>&1 | grep -q "Listening on" && break
  [ "$i" = 90 ] && die "ticket_v2_api_${N}_app が起動しません (docker logs ticket_v2_api_${N}_app を確認)"
  sleep 2
done
# 既知: env2 由来の promoter shard_1 / _396 は schema_migrations 欠損で migrate が一部失敗する
# (multi-env-setup.md 参照)。main と shard_2 は通るので止めない
docker exec "ticket_v2_api_${N}_app" bundle exec rails db:migrate || echo "  ⚠️ db:migrate が一部失敗 (既知の shard 欠損なら無視可)"
docker exec "ticket_v2_api_${N}_app" bundle exec rails db:test:prepare || echo "  ⚠️ db:test:prepare 失敗"

# ------------------------------------------------------------------
step "[8/10] フロントを起動 (project 名 $FRONT_P)"
"${COMPOSE_FRONT[@]}" up -d

# ------------------------------------------------------------------
step "[9/10] 共有 memory / hub の symlink（~/www 版は省略）"
DOMAIN="corichlocal$N"
step "[10/10] /etc/hosts（~/www 版は自動で足さない。手で追記する）"
echo "  ⚠️ /etc/hosts に $DOMAIN.co・$DOMAIN.me 系を env4 の行に倣って追記してください"

# reCAPTCHA のサイトキーは全 env 共通で、許可ドメインは Google 側 (reCAPTCHA 管理画面) で持つ。
# 未登録だとログイン画面に「サイトキーのドメインが無効です」と出てログインできない (2026-10-05 env4 で発生)。
# ここでは直せないので検査だけする (anchor エンドポイントが無効ドメインにエラー文を返す)
step "[検査] reCAPTCHA の許可ドメインに $DOMAIN.co が入っているか"
RK="$(grep -h '^VITE_RECAPTCHA_SITE_KEY=' "$NEW/ticket_v2/.env.development" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' \r')"
if [ -z "$RK" ]; then
  echo "  (site key 未設定のため skip)"
else
  CO="$(printf '%s' "http://$DOMAIN.co:$((5173 + 10 * (N - 1)))" | base64 | tr '+/' '-_' | tr -d '=')"
  ANCHOR="$(curl -s --max-time 15 "https://www.google.com/recaptcha/api2/anchor?ar=1&k=$RK&co=$CO&hl=ja&v=&size=normal" || true)"
  if echo "$ANCHOR" | grep -q "recaptcha-token"; then
    echo "  OK"
  elif echo "$ANCHOR" | grep -q "ドメインが無効\|Invalid domain"; then
    echo "  ⚠️ 未登録: reCAPTCHA 管理画面 (https://www.google.com/recaptcha/admin) でこの site key の"
    echo "     ドメインに $DOMAIN.co と $DOMAIN.me を足すまで、env$N ではログインできません"
  else
    echo "  ? 判定できませんでした (通信エラー等)"
  fi
fi

echo ""
echo "✅ env$N 作成完了: $NEW"
echo "確認: http://$DOMAIN.co:$((5173 + 10 * (N - 1)))/mypage/setting"
