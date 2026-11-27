# ticket_v2_hub（環境1〜6の12枠を取りまとめる場所）

2026-11-25 作成。ホーム（git 管理外）に置く個人用の説明。hub の workspace にある `CLAUDE.local.md` からここを参照する。

## これは何か

- tmux `ticket_v2_project` セッションの **monitor タブの1〜12枠**（環境1〜6の Claude と Codex。1環境1組）を取りまとめるための workspace
- 自分ではチケットの実装・検証をしない。**状態の把握・依頼の送付・完了待ち・結果の集約・次の割り振り**だけを行う
- 新しいリポジトリではなく、`ticket_v2_project` を別の場所に clone したもの

## 置き場所と構成

| 項目 | 値 |
|---|---|
| workspace | `~/www/ticket_v2_hub`（`ticket_v2_project` の clone。release） |
| サブリポ | `ticket_v2`・`ticket_v2_api`（clone のみ。release。コードを読むためだけ） |
| 環境番号 | **なし**（hub）。起動時フローの「環境番号」は「hub」と宣言する |
| Docker | **なし**。コンテナ・DB・Redis・サーバーは作らない・起動しない |
| メモリ | `~/.claude/projects/-Users-piyoh-www-ticket-v2-hub/memory` → `~/.local/share/ticket-v2/memory`（環境1〜6と共有） |
| git 管理外の設定 | `.claude/settings.local.json`・`.codex/config.toml`・`.kiro/settings/mcp.json` は環境4からコピー（4環境とも同じ内容） |
| Codex の信頼設定 | `~/.codex/config.toml` に `/Users/piyoh/www/ticket_v2_hub` を追加済み |
| 起動 | `cd ~/www/ticket_v2_hub && bin/claude ticket_v2 ticket_v2_api --permission-mode auto`（`bin/codex` も同じ引数） |

## 管理する12枠（monitor タブ）

定義は `~/.tmuxp/ticket_v2_project/monitor.txt`。奇数枠が Claude、偶数枠がその相方の Codex（`CODEX_SLOT`）。

| 枠 | 環境 | 中身 |
|---|---|---|
| 1 ↔ 2 | 環境1 `~/www/ticket_v2` | Claude（continue）↔ Codex（continue） |
| 3 ↔ 4 | 環境2 `~/www/ticket_v2_second` | 同上 |
| 5 ↔ 6 | 環境3 `~/www/ticket_v2_third` | 同上 |
| 7 ↔ 8 | 環境4 `~/www/ticket_v2_fourth` | 同上 |
| 9 ↔ 10 | 環境5 `~/www/ticket_v2_fifth` | 同上 |
| 11 ↔ 12 | 環境6 `~/www/ticket_v2_sixth` | 同上 |

- **2026-11-27 に1環境1組に組み替えた**（それまでは環境1・2が2組、環境3・4が1組で Codex は read-only）。環境5・6は `bin/create-env-www.sh N --config-from env4 --db-from env4`（devtools の `tools/create-env.sh` の ~/www 版。サブ repo は ticket_v2・ticket_v2_api だけ、hosts は手で追記）で作った。Chrome のポートは ~/.zshrc で環境5=9245・環境6=9246。どの環境も開発・設計に使うので、`/na-next` が空き枠を選ぶ順は枠の番号順（server.py の `SLOT_PREFER`）。Codex は全部書き込みあり
- tmux のタブ（`~/.tmuxp/ticket_v2_project.yaml`。変更前は `.bak-20261127`）: 0 zsh・1 vim（環境1〜6の api・app の12枠）・2 monitor・3 envs（環境1〜6のワークスペース6枠）・4 servers（環境1〜6 × api server・app server・sqs の18枠。`~/bin/local-server` とダッシュボードはここの枠を使う。定義は `servers.txt`）。どのタブも ★ MAIN は hub（`--main-first`・`start_directory: ~/www/ticket_v2_hub`）。env1〜env4 タブは廃止（DB コンソール・ログのコマンドは `env*.txt.bak-20261127`）
- **hub は monitor の番号無しの枠（★ MAIN。`claude-monitor` を実行した元の枠）に置く**（2026-11-25 決定）
  - `~/.tmuxp/ticket_v2_project.yaml` の monitor タブに `start_directory: ~/www/ticket_v2_hub` を指定し、起動コマンドを履歴に積むだけにした（↑ = continue、↑↑ = new）。変更前は `ticket_v2_project.yaml.bak-20261125`
  - monitor タブの `claude-monitor` には `--main-first` を付けているので、tmuxp を読み込んだ直後から番号無しの枠（★ MAIN＝hub）がメインに出る（2026-11-25〜。付けない他のタブは従来どおり [1] がメイン）。[n] を見た後で MAIN に戻すには、表示中の番号（Alt+n）をもう一度押す
- 枠番号とペイン ID（`%NN`）の対応はフォーカス切り替えのたびに変わる。**送る直前に毎回 `tmux_link.py list` で引き直す**

## hub がやること・やらないこと

やること:
- 12枠の一覧と状態（実行中・入力待ち・空き）、各枠のチケット番号・段階の把握（`tmux_link.py list`・枠タイトル・開発ダッシュボードの「対応中」）
- **`/na-slots-status [枠…]`**（2026-11-26〜）: 全部の枠の今の状態を Claude が表で答える（hook で止めない・ポップアップを使わない）。材料は `bin/hub_slots.py`（/api/panes・/api/watch・各枠の画面・statusline の最後の動き・ct-fix-loop の state.json・autopilot.json・docker.json）。先頭に「あなたの番」（質問・確認待ち・未送信の入力）、表は 枠・チケット・状態・何を待っているか・最後の動き・次に止まる所、最後に気になる点と次の一手（コマンドの形の提案だけ。送らない）
  - **ユーザーが見るときは `/na-list`**: Claude の枠（奇数枠）だけを1枠2行（状態・チケット・ブランチ・会話量・完了時刻／最後の応答の末尾）で画面に出す。`/na-to` と同じ hook（`na_to.py --hook`）が表示してプロンプトを止めるので、hub の会話を消費しない。スキル本体 `hub/skills/na-list/SKILL.md` を hub の `.claude/skills/na-list` からシンボリックリンク（`.git/info/exclude` 済み）
  - **一覧はポップアップで操作する**（2026-11-25〜）: `/na-list`・`/na-list 枠 [行数]`・`/na-watch [refresh]`・`/na-redmine [引数]`・`/na-order`（引数なし）は、hub の tmux のクライアントにポップアップ（94%×90%）を開き、その中の `hub_tui.py` がデータを取って描く（hook はすぐ返し、hook の文は「ポップアップで開きました」の1行だけ）。一覧: ↑↓ j k 選ぶ・→ l 選んだ行を全文に広げる・← h たたむ・a 全部広げる/たたむ・Enter 詳細・o ブラウザ・r 取り直す（15 秒ごとにも取り直す）・g G 先頭/末尾・q Esc 閉じる。詳細（長い行は折り返して全部出す）: ↑↓ PgUp PgDn スクロール・r・o・Esc ← q で一覧へ戻る。Enter の行き先: /na-list → その枠の詳細（要約・監視のカード・画面の末尾 80 行）／/na-watch → チケットのカード・自動の依頼の結果と直近5件の記録・枠の詳細／/na-redmine → 件名・優先度・ステータス・待ち・作業中の枠・最新コメント（ダッシュボードの取得分。先頭約200字）・URL・枠の詳細／/na-order → /na-redmine と同じ詳細。/na-order の一覧だけ K J（Shift）で選んだチケットを1つ上・下へ動かし、x で固定から外す（order.json にすぐ保存。監視の対象も変わる。引数ありの /na-order は従来どおり hook の文）。部品は `hub_popup.py`（色・カード・枠の詳細）と `hub_pager.py`（キーの読み取り。Esc の後 50ms 続きが無ければ Esc）。hook の文（Claude Code が必ず黄色で出す）で出すのは、ポップアップを開けない・引数が誤りのときだけ
  - **1枠だけ詳しく見るときは `/na-list 枠 [行数]`**（例 `/na-list 7`・`/na-list 7 60`。偶数の Codex の枠も可）: その枠の1枠2行の要約、監視（`/na-order` で固定したチケット）に載っていれば流れの印と自動の依頼の状況、画面の末尾（入力欄から下を除く。既定 30 行・最大 150 行）を出す。実装は `hub_status.py` の `detail_text`・`screen_body`
  - **ct-redmine の前の過去のセッションの確認**（個人の `~/.claude/settings.json` の UserPromptSubmit hook → `~/.local/share/ticket-v2/bin/ticket_sessions.py --hook`。全環境の Claude に効く。Codex は対象外）: hub（MAIN）から `/na-to`・`/na-next`・自動の依頼で `/ct-redmine 番号`（参照だけ）を送ったときだけ（`na_to.py` が `hub/sent/pane-<n>.json` に送った印を書き、hook が2分以内・同じ文なら hub からと判断。枠で直接打ったときは聞かない）、`~/.claude/history.jsonl` からその番号が出てくる過去のセッション（hub の会話・`/na-` の指示は除く）と `~/.claude/tmp/ct-handoff/番号_session_handoff.md` を探し、見つかれば Redmine を読む前に「開き直す（C-r の ctrl-o 相当。同じ workspace で、いま別の枠で開いていないものだけ）・会話を読み込んでから続ける（ctrl-t 相当。`handoff` で直近 10 往復を書き出す）・引き継ぎを読む・使わずに新しく読む」を聞く。hub から送ったときもその枠で質問になって止まる（`/na-watch` は質問中）
  - hub の Claude が見るときは `python3 ~/.local/share/ticket-v2/hub/bin/hub_status.py`（12枠を1行ずつ要約。--active で起動中だけ、--compact で /na-list と同じ形）。詳しく見る枠だけ `tmux_link.py read %ID`
- Redmine のチケットの把握（2026-11-25〜）
  - **ユーザーが見るときは `/na-redmine [件数] [優先度…] [全部] [再取得]`**: 自分担当の未完了（新規登録・進行中・フィードバック）とウォッチ中（終了・解決・却下以外。プロジェクトを問わない）を1件2行で画面に出す。1行目は【優先度】・ステータス・件名・作業中の枠（[n] 状態 スキル名）、2行目は待ち・ブロック先（未完了の相手だけ）・最終更新（自分/他・日時）・最新コメントの冒頭（自分のコメントなら「自:」）。`/na-list` と同じ hook が表示するので hub の会話を消費しない
    - 優先度を指定しないときは、件がある優先度の上から2段だけ（今すぐ・急いで。今すぐが無ければ急いで・高め）。`/na-redmine 高め以上`・`/na-redmine 今すぐ 急いで 10`・`/na-redmine 全部`。引数は英語でも書ける（`now`・`urgent`・`high`・`normal`・`low`・`high+`・`all`・`refresh`）
    - 並び（2026-11-25 決定）: ① 固定（`/na-order` の順。優先度の絞り込みに関係なく必ず出る）→ ② 着手可（未完了の待ちがなく、最新コメントが自分以外）→ ③ 相手の番（最新コメントが自分）→ ④ 待ち（未完了の相手あり）。②〜④の中は優先度→作業中→最終更新の古い順。期日・対象バージョンは使っていない（担当分で未入力のため）
  - **固定の順（緊急の割り込みなど）は `/na-order`**: 引数なし=表示、`/na-order 14921 14926`=この順で置き換え、`/na-order 15026 1`=1番目に入れる（2つ目が3桁以下なら順位）、`+番号`=末尾に足す、`-番号`=外す、`clear`=全部外す。担当外の番号も指定できる（[一覧外] の印）。存在しない番号は ⛔ で止めて変えない。終了・解決・却下になったら次の表示で自動で外す
    - hub だけで持つ（`hub/order.json`。Redmine の優先度・ダッシュボードには書かない。copy-to-workspace / copy-to-home の対象外）。処理は同じ hook（`hub_redmine.py` の `order_cmd`。CLI は `hub_redmine.py --order …`）。スキル本体 `hub/skills/na-order/SKILL.md` を hub の `.claude/skills/na-order` からシンボリックリンク（`.git/info/exclude` 済み）
    - データは開発ダッシュボードの `/api/redmine`（5分キャッシュ。`再取得` で取り直し）を localhost から読む。Redmine への問い合わせ・キャッシュ・枠との対応づけはダッシュボードの1か所だけ（hub は Redmine に直接問い合わせない）。ダッシュボードが止まっていると ⛔ を出す
    - 構成: 整形 `hub/bin/hub_redmine.py`（hub の Claude が見るときも `python3 … hub_redmine.py [件数] [優先度…] [--json]`）。スキル本体 `hub/skills/na-redmine/SKILL.md` を hub の `.claude/skills/na-redmine` からシンボリックリンク（`.git/info/exclude` 済み）
  - ダッシュボードの Redmine 欄にもウォッチ分（区切り「ウォッチ中」）と、もっと見るの絞り込みに優先度（〜以上も）を足した。ダッシュボードは全優先度を出す（上から2段に絞るのは `/na-redmine` だけ）
- 固定したチケットの監視（2026-11-25〜。設計は https://claude.ai/artifact/83S9a5vy7eEcttdDvrL9jz の「A 見る」）
  - 対象は `/na-order` で固定したチケット。判定は開発ダッシュボードの常駐ループ（server.py の `watch_loop`。20 秒ごと）が行い、結果を `/api/watch` と `hub/watch.json` に書く。hub の Claude は常駐しない
  - 判定するもの: 担当の枠（Claude の枠のうち、そのチケットを作業中のもの）・状態・スキル単位の段階・03_progress.md のフェーズ・PR・レビュー
    - 状態: 処理中 / 確認待ち（許可）/ 確認待ち（質問。スキルの返答が質問で終わった）/ 確認待ち（次の指示。流れのスキルが終わった）/ 入力待ち / 枠なし
    - 段階: 環境1〜6の Claude の会話ログ（`~/.claude/projects/*/*.jsonl`。直近14日）から、チケット番号付きのスキル実行（`/ct-… 番号`・Skill ツール）とその終わり（end_turn が質問かどうか）を拾い、流れ redmine→analyze→architect→(sweep)→(scope)→planner→issue-docs→ship-loop→finish の各段に印を付ける。後の段が動いていて記録の無い必須の段は「✗ 記録なし」
  - 見る場所: ダッシュボードの先頭の「監視（/na-order）」欄（20 秒ごとに更新。確認待ちの行は黄色）と、hub の **`/na-watch [refresh]`**（同じ hook で表示。会話を消費しない。CLI は `hub_watch.py [--json]`）
  - 通知（状態が変わったときだけ。固定した直後とダッシュボードの起動直後は今の状態を記録するだけ）:
    - tmux のステータス行の右に「確認待ち N」（`@hub_attention`。セッションの `status-right` の先頭に書式を足す。tmuxp を読み直して消えても次の判定で足し直す）
    - tmux の各クライアントに数秒のメッセージ（`display-message`）
    - Slack DM（`~/.claude/hooks/slack-dm.sh`）: 確認待ちに変わったとき・レビュー依頼が来た／修正依頼が付いたとき
    - 前回の状態は `hub/watch_notify.json`（watch*.json は copy-to-workspace / copy-to-home の対象外）
  - 確かめるときは `/api/watch?tickets=14926,14747`（固定の順を使わず判定だけ。記録・通知はしない）
- 自動の依頼（2026-11-25〜。B 次のスキル・C 資料の後のコミット・F レビュー）。判定と送信はダッシュボードの同じ常駐ループ（1回に1件。送信は `na_to.py` なので、偶数枠・処理中・入力欄に文字がある枠・本番系の枠には送らない）
  - **`/na-next 番号 [枠] [sweep] [scope] [model=…] [effort=…] [dry]`**: 止まっている所から次のスキルを頼み、以後そのチケットを自動の依頼の対象にする（固定しただけでは始めない）。枠を指定しなければ空いている Claude の枠（入力待ち・作業中のチケット無し・`/na-slot off` で外していない・他のチケットに割り当てていない）を、枠の番号順（[1]→[3]→…→[11]。2026-11-27 まで設計用の環境3・4 → 環境1・2）に選ぶ。**起動中の空き枠が無ければ、Claude が未起動の奇数枠（シェルのまま）で `monitor.txt` のその枠のコマンドから `--continue` を外して新しい会話として起動し、入力待ちになったら依頼を送る**（autopilot.json の `pending`。4分たっても入力待ちにならなければ tmux・Slack に知らせる。2026-11-26〜）。**新しい会話のまま（まだ何も入力していない。statusline の記録ファイルが未作成）の枠は、前の会話で付けたタイトル（#番号）や autopilot.json の古い割り当てが残っていても空きとみなす**（起動し直した・/clear した枠。送ったら、その枠に残っていたほかのチケットの割り当てを外す）。1チケット1枠（作業中の枠と違う枠は指定できない）。`dry` は送らずに判定だけ
    - 次のスキル: なし→ct-redmine→ct-analyze→ct-architect→（sweep・scope を付けたら ct-sweep→ct-scope）→ct-planner→ct-issue-docs→コミット
    - 自動で進めるのは ct-redmine の後（→ct-analyze）・ct-sweep／ct-scope の後（→次）・ct-issue-docs の後（→コミット）。**ct-analyze・ct-architect・ct-planner の後は止めて確認待ち**として知らせる（`/na-next 番号` で次へ。architect の後に `sweep`・`scope` を付けて決める）。途中の質問も確認待ち。ct-ship-loop 以降は /na-go
    - ct-analyze の依頼文には「初期調査はステージング（団体 naga3）・テスティングは団体 nagayoshi・ローカルの DB・Redis・サーバーが要るときだけ hub_docker.py wait で順番待ち」を添える
    - コミット（C）は `/ct-commit 番号 issue docs だけをコミット。ブランチは環境の CLAUDE.local.md の決まり（設計だけなら design/番号）。push しない` を1回だけ
    - 頼まないもの: 次のスキルがすでに動いた記録があるとき（終わったチケットで ct-redmine をコメントに使った等）・ブランチ／PR／03_progress.md があるのに流れの記録が足りないとき（記録の外で進めたチケット）・割り当てた枠と違う枠で作業しているとき
  - レビュー（F）: 固定していないチケットのレビュー依頼・修正依頼は知らせだけ（tmux・Slack DM。「/na-order で順番に入れると ct-pr-turn を自動で頼む」）。**固定したら** `/ct-pr-turn <PR の URL> #番号` を自動で頼む（作業中の枠、無ければ空いている枠。修正依頼は環境1・2の枠だけ）
  - 自動の依頼の失敗（枠が無い・送れない）は tmux と Slack DM で1回だけ知らせる
  - **本番の問題のチケット**: 件名・説明に「本番・障害・負荷・急増・検知・アラート・ECPU・タイムアウト・遅い・エラー・問い合わせ」などがあれば本番の問題と自動で判断し、ct-analyze を頼む前に **そのチケットで最初の1回だけ** tmux と Slack で確かめる（送らずに止まる）。`/na-next 番号 prod` で本番の DB・Redis・ログの読み取り専用の精査を依頼文に足して送る、`noprod` で足さずに送る（答えは autopilot.json の `prod` に残り、以後は聞かない）
  - 送信（na_to.py）は、入力待ちが3秒続き入力欄が空のままかを確かめてから送る（処理の合間の一瞬の入力待ちで送ると「Queued」になる）
  - 番号を省いて枠だけ（`/na-next 7`・`/na-go 1`）を指定すると、その枠で作業中のチケットを使う（枠のタイトル `#番号` か会話の作業番号。複数・不明なら止まる）。偶数の枠（Codex）は相方の Claude の枠（-1）に読み替える
  - **モデルと思考の深さの自動選択**（2026-11-25〜）: 自動で頼むとき（/na-next・/na-go・続きの自動の依頼）は、スキルの前に `/model`・`/effort` を枠へ送る。表は `server.py` の `MODEL_TABLE`
    - ct-redmine は sonnet・medium。ただしチケットの説明・コメントに Google Slides の URL か、画像・PDF の添付があれば opus・high（画像を読むので）
    - ct-analyze・ct-architect・ct-planner・ct-pr-turn・ct-fix-loop は opus・high。ct-issue-docs・ct-ship-loop・ct-finish は opus・medium。ct-sweep・ct-scope は sonnet・medium。コミットは sonnet・low
    - `sweep`・`scope` 付きのチケットは ct-architect・ct-planner を xhigh に。同じスキルを頼み直したら1段上げる（sonnet→opus、深さ +1）。`model=fable`・`effort=xhigh` を付けるとその1回だけ上書き
    - `/model`・`/effort` は `~/.claude/settings.json` の既定（model・modelSettings）も書き換えるので、送った直後にダッシュボードが元へ戻す（戻しても枠の会話のモデルはそのまま）
    - 会話の途中で `/model` を送ると「Switch model?（履歴を読み直すので遅くなる）」の確認が出るので、ダッシュボードが Enter で Yes を選ぶ
  - `/na-next`・`/na-go` の決まった引数の後ろに書いた文（例: `/na-next 15018 1 15026と内容が被ってるので先に確認して`）は「補足（hub から）: …」として依頼文の末尾に付けて送る。2つ目のチケット番号から後ろも補足になる
  - スキルの返答の最後が「？」のほか「〜か。」（進めますか。など）で終わったら質問とみなし、次へ進めずに確認待ち（質問）として知らせる
  - **レビューのチケット**: `/na-next` で開始したチケットに自分の PR が無く、他の人のオープンな PR（タイトルに #番号）があれば、GitHub でレビュアーに指定されていなくてもレビューとみなす。レビューのチケット（レビュアー指定も含む）は **ct-redmine → ct-pr-turn** の順（ct-redmine が済んでいれば ct-pr-turn から）。ct-redmine が終わったら autopilot が ct-pr-turn を1回だけ頼み、設計の流れ（analyze→…）は頼まない（autopilot.json の `mode: review`・`review.urls`）。枠で ct-pr-turn を手で始めた場合と、ct-pr-turn の中で動いた ct-sweep なども、流れの自動の依頼をしない
  - 枠の取り違え防止: claude-monitor のフォーカス表示で「[n] → left」になった枠（実体は MAIN など別の枠）は [n] とみなさない。「★ FOCUS [n]」は [n]
  - **`/ct-… 番号`（`/ct-redmine`・`/ct-architect` など番号で始まるもの全部）・`/ct-pr-turn … #番号` を送る前に**（自動の依頼も `/na-to` で手で送るときも）、hub（`na_to.py` の `title_before`）がその枠に `~/bin/tmux-title --pane` で「#番号: 件名」のタイトルを直接付ける（ct-pr-turn は ct-redmine を経ないことがあり、枠を使い回すと ct-architect 等から始まるので、タイトルが前のチケットのまま変わらなかったため。2026-11-26〜）
  - **別のチケットの会話が残っている枠に頼むときは、先に `/clear` する**（server.py の `clear_other`。自動で選んだ枠も指定した枠も。同じチケットの続きは会話を引き継ぐので消さない。新しい会話の枠はそのまま。結果の文に「/clear しました」と出る。2026-11-26 [5] で #15012 の会話のまま #14921 を頼んだため）（枠の Claude に ct-tmux-title を頼まない。会話に残らないので `--continue` で起動し直したときは付け直されない）
  - **`/na-go 番号 [枠] [--branch 名前] [force] [dry]`**（D。2026-11-25〜）: 実装を始める。決まった依頼文2つ（設計ページ r1 q4 の補足のまま）を順に送る
    - 1つ目 `/ct-ship-loop 番号 コーディングはcodexで…ブランチ：feature/番号`（`--branch` で変える）。ct-ship-loop が終わったら（end_turn が質問でない）2つ目 `/ct-finish 番号 sweepは設計時に…アーティファクトにまとめて` を自動で送る。ct-finish が終わったら tmux と Slack DM で「完了」を知らせる（push はしない）
    - 枠: 作業中の枠（1チケット1枠）。無ければ指定した枠、無ければ空いている Claude の枠（枠の番号順）
    - 止めるもの: ct-issue-docs の記録が無い（記録の外で設計したなら `force`）・ct-ship-loop／ct-finish の記録がある（やり直しは `force`）・処理中や確認待ち・**同じ環境のもう一方の Claude の枠が処理中／確認待ち**（同じリポジトリのブランチを切り替えるため。その枠がリポジトリを使わない作業（本番の監視など）なら `force`。2026-11-26 [7] #15043 の本番監視中に [5] で #14921 を始めた）
    - **`force` は上の確認（設計・調査の記録が無い・実装の記録がある・同じ環境の枠が動いている）を全部まとめて飛ばす**。1つのために付けても他も効かなくなるので、付ける前に残りの確認を自分で済ませる
    - 補足の指示に別のチケットを「#番号」で書いても、スキルの引数の**先頭の番号**がそのチケットとして記録される（server.py の `arg_tickets`。先頭に番号が無いときだけ「#番号」。2026-11-26 まで「#番号」が優先で、補足の「[7] #15043 は…」により #14921 の ct-ship-loop が #15043 の作業と記録され、ct-finish を自動で頼まなかった）
    - 実装を始めたチケットは、流れの自動（redmine→analyze 等）の対象から外れる。状態は `autopilot.json` の `go`（stage: ship-loop → finish → done）。監視欄・/na-watch に「実装: ship-loop 中」等
    - API は `POST /api/watch/go {ticket, slot, branch, force, dry, flow}`。スキル本体 `hub/skills/na-go`
  - **流れは2本**（2026-11-26〜）。どちらで進めるかは ct-analyze の後にユーザーが決める（hub は件名から推奨を出す: 「不具合・負荷・エラー・遅い・ECPU・タイムアウト・二重・重複」などがあれば不具合・負荷の流れ。ct-analyze 完了の知らせと /na-watch の「推奨」行に出る）
    - **新規開発**: redmine→analyze→architect→(sweep)→(scope)→planner→issue-docs→ship-loop→finish。ct-ship-loop は最初に `ct-test-design` で全フェーズ分のテスト設計表（issue docs の `test_design.md`）を作り、各フェーズは「Codex がテスト（RED）→ Codex が実装（GREEN）→ Claude が両方をレビュー → Claude がテストの説明を日本語で書き直しコメントを足す」。実装で変わったら設計表もその都度直す（止まらない）
    - **不具合・負荷**: redmine→analyze→**fix-loop**→finish。`/na-go 番号 fix` で始める（ct-analyze の記録が必要。無ければ `force`）。個人スキル `~/.claude/skills/ct-fix-loop`: 基準の実測 → 施策（Codex）→ 実測（Codex。負荷は計測、不具合は再現の手順）→ Claude のレビュー を「必ず直す」「できれば」が0件まで → **止まって確認** → 設計書 → テスト設計（Codex のレビューで OK まで）→ Codex がテスト（英語・コメントなし）→ Claude のレビュー → Claude が日本語化とコメント → ct-finish → **push の確認で止まる**
    - 施策の進み具合は ct-fix-loop が `~/.claude/tmp/fix-loop/<番号>/state.json` に書き、監視欄・/na-watch の「施策」行に「施策 第2回・レビュー・指摘3件」「（施策の結果の確認待ち）」のように出る。終わり（state.json の stop=push か step=done）で tmux・Slack に完了を知らせる
    - `/na-next 番号 fix|new` でも流れを選べる（autopilot.json の `plan.flow`）。fix にすると ct-analyze の後は自動で進めず、`/na-go 番号 fix` を案内する
    - ct-finish は両方の流れの最後に使い、テスト設計表との照合・変異検査（一時コミットの後の clean な作業ツリーで1件ずつ入れて戻す）・2pass レビュー＋Codex の独立レビューとの照合（「必ず直す」「できれば」は Codex が直し、「任意」は一覧で報告）・ブラウザでの確認（録画と DB・Redis・ログの監視。画面が変わらなければ理由を書いて省く）を行う。途中では止まらず、最後の push の確認だけで止まる
    - 個人スキルの編集前の控え: `~/.claude/tmp/skill-backup-20261126-flow/`
  - **`/na-slot [off|on 枠…]`**: 自動で割り当てる枠から外す・戻す（例 `/na-slot off 11 12`。`hub/slots.json`）
  - 状態: `hub/autopilot.json`（開始したチケット・割り当てた枠・sweep/scope・処理済みの区切り・送信の記録）。`/na-watch` とダッシュボードの監視欄に「自動 [枠] スキル 送信/失敗 時刻」を出す
  - **一時停止**（2026-11-26〜）: `hub/paused` というファイルがある間は、自動の依頼（次のスキル・コミット・ct-pr-turn・/na-go の続き）を送らない（server.py の `autopilot()` の先頭で見る）。止めるのは `date > ~/.local/share/ticket-v2/hub/paused`、再開は削除。各枠の今の作業は止まらないので、止めたい枠には別に `/na-to 枠 …` で止まるよう頼む（2026-11-26 使用量の制限の前に [3]・[9] を止めて 18:01 に再開した）
  - スキル本体 `hub/skills/na-next`・`na-slot`（hub の `.claude/skills/` からリンク。`.git/info/exclude` 済み）。API は `POST /api/watch/next {ticket, slot, sweep, scope, dry}`
- 開発用サーバー（Docker）の順番待ち（E。2026-11-25〜）
  - メモリの都合で、ローカルの api・app・sqs は同時に1環境だけ。**テスト・ブラウザでの確認・ローカルの DB/Redis を見る作業の直前に、各環境の Claude が `python3 ~/.local/share/ticket-v2/hub/bin/hub_docker.py wait <番号>`**（run_in_background。終了コード 0 = 使ってよい・3 = まだ待ち→もう一度・1 = 失敗）、終わったら `release <番号>`。コードを書く・読む作業は待たない（実装は同時に複数進めてよいので、/na-go の1件ずつの制限は外した）
  - wait は順番が来たら、他の環境のサーバーを `~/bin/local-server down` し、自分の環境を `up` する（環境2も対象。2026-11-25 決定）。release ではサーバーを止めない（次の人の wait が切り替える）
  - 順番は /na-order の順（固定したものが先）、固定していないものは来た順。同じチケットの wait は使用中ならすぐ返る。5分呼び直さない待ちは外す。環境は実行したフォルダから判定（hub では使えない。`--env envN` で指定可）
  - 譲る: 使用中のチケットの枠が 15 分止まって（質問・入力待ち・枠が無い）いるか、**45 分 `wait` を呼んでいない（処理中でも。サーバーを使う直前に毎回 wait を呼ぶ決まりなので、使っていない見込み）**とき、待っている人がいれば、ダッシュボードの常駐ループが使用中を外し、tmux と Slack DM と使用中だった枠（`na_to.py --busy`。処理中でも途中で読む）に知らせる（2026-11-26 30分→15分・45分を追加。#14747 が処理中のまま1時間半返さず #15047 が待ち続けた）（記録は docker.json の log。`hub_docker.py status` に直近3件）
  - 手順は個人スキル `~/.claude/skills/ct-ship`・`ct-ship-loop`・`ct-finish`・`ct-pr-turn` の「開発用サーバーの順番待ち」の節に書いた（チーム共有の ct-analyze は書き換えず、依頼文で伝える）。編集前の控えは `~/.claude/tmp/skill-backup-20261125-docker/`
  - 見る: **`/na-server-status`**（hook の文。使用中・経過時間・最後の wait・譲るまでの残り・順番待ち・各環境のサーバー・直近6件の記録・枠の番号と状態。`/na-server-status release 番号` で使用中・順番待ちから外す。2026-11-26〜）・`hub_docker.py status`・監視欄の先頭・/na-watch の2行目。状態は `hub/docker.json`・`docker.lock`（copy の対象外）
- Claude の枠（奇数枠）への依頼の送付と完了待ち（2026-11-25 決定: hub が送るのは Claude の枠だけ）
  - **ユーザーが送るときは `/na-to <枠番号> <指示>`**（例: `/na-to 3 /ct-redmine 14926`）。hook が送信してプロンプトを止めるので、hub の Claude は動かず hub の会話を消費しない。結果は「UserPromptSubmit operation blocked by hook: na-to ✅ 送信しました …」と画面に出る（"blocked" は正常）。`/na-to 3 /ct-` のように途中で `/` を打つと候補が出る（途中の `/ct-…` は hub では実行されず、文字として送り先に届く）。**処理中の枠にも送れる**（Claude Code は処理中の入力を今の処理の途中で読む。2026-11-25〜）。送らないのは確認待ち（確認の画面に文字を打つと選択肢を選んでしまう）・入力欄に未送信の文字がある・未起動・本番系の枠。自動の依頼（`/na-next`・`/na-go`・autopilot）は先に `/model`・`/effort` を送るので、これまでどおり入力待ちが3秒続くときだけ送る
    - 送らずに止めるもの: 偶数枠（Codex）・Claude 未起動・処理中・確認待ち・入力欄に未送信の文字がある枠・本番系の枠。入力欄の薄い文字（Claude Code の次の入力の候補）は未送信の扱いにしない
    - 構成: 本体 `hub/bin/na_to.py`（`--hook` で hook 用、`--dry-run` で送信直前まで判定だけ）。スキル本体 `hub/skills/na-to/SKILL.md`（「/」の候補に出すためだけ。`disable-model-invocation: true`）を hub の `.claude/skills/na-to` からシンボリックリンク（`.git/info/exclude` 済み）。hook は hub の `.claude/settings.local.json` の `UserPromptSubmit`
    - 受け付けの判定は「入力欄が空になったか」（tmux_link.py send の「処理中が見えるまで最大36秒」は、すぐ終わる返答で待ち切るため使わない）
  - hub の Claude が自分で送るときは `python3 .claude/skills/ct-tmux-link/scripts/tmux_link.py send %NN --file <依頼文>` → `wait` → `hub_status.py` か `read`
  - Codex の枠（偶数枠）には hub から送らない。各 Claude が相方の Codex に `codex_send.py --kind` で送る（モデル選択・`--new` の判断も各 Claude）。hub は Codex の枠を状態の確認のためだけに見る
- 結果の集約と報告、次のチケットの割り振りの提案
- コードを読む（判断材料として。読む前に `pull-all ~/www/ticket_v2_hub`）

やらないこと:
- サーバー・Docker・DB・SQS ワーカーの起動停止（開発ダッシュボードか各環境の枠で行う）
- チケットの実装・コミット・push・ブラウザでの動作確認（各環境の枠に任せる）
- hub の `ticket_v2`・`ticket_v2_api` でのブランチ作成（release のまま読むだけ）
- 本番系の枠（タイトルに prd / production / 本番 / bat0N）への送信

## 未決事項

- 開発ダッシュボードに hub を表示するか（今は環境1〜6だけ。hub は環境ではないので登録していない）
- ~~12枠の状態をまとめて出す hub 専用のコマンド・スキルを作るか~~ → 2026-11-25 `hub/bin/hub_status.py` を作成。スキル化はしない（個人用で hub でしか使わず、スキルにするとチーム共有リポへのコミットと全環境への配布になるため。README に書けば hub の Claude は起動時に読む）
