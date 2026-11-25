# ticket_v2_hub（環境1〜4の12枠を取りまとめる場所）

2026-11-25 作成。ホーム（git 管理外）に置く個人用の説明。hub の workspace にある `CLAUDE.local.md` からここを参照する。

## これは何か

- tmux `ticket_v2_project` セッションの **monitor タブの1〜12枠**（環境1〜4の Claude と Codex）を取りまとめるための workspace
- 自分ではチケットの実装・検証をしない。**状態の把握・依頼の送付・完了待ち・結果の集約・次の割り振り**だけを行う
- 新しいリポジトリではなく、`ticket_v2_project` を別の場所に clone したもの

## 置き場所と構成

| 項目 | 値 |
|---|---|
| workspace | `~/www/ticket_v2_hub`（`ticket_v2_project` の clone。release） |
| サブリポ | `ticket_v2`・`ticket_v2_api`（clone のみ。release。コードを読むためだけ） |
| 環境番号 | **なし**（hub）。起動時フローの「環境番号」は「hub」と宣言する |
| Docker | **なし**。コンテナ・DB・Redis・サーバーは作らない・起動しない |
| メモリ | `~/.claude/projects/-Users-piyoh-www-ticket-v2-hub/memory` → `~/.local/share/ticket-v2/memory`（環境1〜4と共有） |
| git 管理外の設定 | `.claude/settings.local.json`・`.codex/config.toml`・`.kiro/settings/mcp.json` は環境4からコピー（4環境とも同じ内容） |
| Codex の信頼設定 | `~/.codex/config.toml` に `/Users/piyoh/www/ticket_v2_hub` を追加済み |
| 起動 | `cd ~/www/ticket_v2_hub && bin/claude ticket_v2 ticket_v2_api --permission-mode auto`（`bin/codex` も同じ引数） |

## 管理する12枠（monitor タブ）

定義は `~/.tmuxp/ticket_v2_project/monitor.txt`。奇数枠が Claude、偶数枠がその相方の Codex（`CODEX_SLOT`）。

| 枠 | 環境 | 中身 |
|---|---|---|
| 1 ↔ 2 | 環境1 `~/www/ticket_v2` | Claude（continue）↔ Codex（continue） |
| 3 ↔ 4 | 環境1 | Claude（new）↔ Codex（new） |
| 5 ↔ 6 | 環境2 `~/www/ticket_v2_second` | Claude（continue）↔ Codex（continue） |
| 7 ↔ 8 | 環境2 | Claude（new）↔ Codex（new） |
| 9 ↔ 10 | 環境3 `~/www/ticket_v2_third` | Claude ↔ Codex（read-only） |
| 11 ↔ 12 | 環境4 `~/www/ticket_v2_fourth` | Claude ↔ Codex（read-only） |

- **hub は monitor の番号無しの枠（★ MAIN。`claude-monitor` を実行した元の枠）に置く**（2026-11-25 決定）
  - `~/.tmuxp/ticket_v2_project.yaml` の monitor タブに `start_directory: ~/www/ticket_v2_hub` を指定し、起動コマンドを履歴に積むだけにした（↑ = continue、↑↑ = new）。変更前は `ticket_v2_project.yaml.bak-20261125`
  - monitor タブの `claude-monitor` には `--main-first` を付けているので、tmuxp を読み込んだ直後から番号無しの枠（★ MAIN＝hub）がメインに出る（2026-11-25〜。付けない他のタブは従来どおり [1] がメイン）。[n] を見た後で MAIN に戻すには、表示中の番号（Alt+n）をもう一度押す
- 枠番号とペイン ID（`%NN`）の対応はフォーカス切り替えのたびに変わる。**送る直前に毎回 `tmux_link.py list` で引き直す**

## hub がやること・やらないこと

やること:
- 12枠の一覧と状態（実行中・入力待ち・空き）、各枠のチケット番号・段階の把握（`tmux_link.py list`・枠タイトル・開発ダッシュボードの「対応中」）
  - **ユーザーが見るときは `/na-list`**: Claude の枠（奇数枠）だけを1枠2行（状態・チケット・ブランチ・会話量・完了時刻／最後の応答の末尾）で画面に出す。`/na-to` と同じ hook（`na_to.py --hook`）が表示してプロンプトを止めるので、hub の会話を消費しない。スキル本体 `hub/skills/na-list/SKILL.md` を hub の `.claude/skills/na-list` からシンボリックリンク（`.git/info/exclude` 済み）
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
    - 段階: 環境1〜4の Claude の会話ログ（`~/.claude/projects/*/*.jsonl`。直近14日）から、チケット番号付きのスキル実行（`/ct-… 番号`・Skill ツール）とその終わり（end_turn が質問かどうか）を拾い、流れ redmine→analyze→architect→(sweep)→(scope)→planner→issue-docs→ship-loop→finish の各段に印を付ける。後の段が動いていて記録の無い必須の段は「✗ 記録なし」
  - 見る場所: ダッシュボードの先頭の「監視（/na-order）」欄（20 秒ごとに更新。確認待ちの行は黄色）と、hub の **`/na-watch [refresh]`**（同じ hook で表示。会話を消費しない。CLI は `hub_watch.py [--json]`）
  - 通知（状態が変わったときだけ。固定した直後とダッシュボードの起動直後は今の状態を記録するだけ）:
    - tmux のステータス行の右に「確認待ち N」（`@hub_attention`。セッションの `status-right` の先頭に書式を足す。tmuxp を読み直して消えても次の判定で足し直す）
    - tmux の各クライアントに数秒のメッセージ（`display-message`）
    - Slack DM（`~/.claude/hooks/slack-dm.sh`）: 確認待ちに変わったとき・レビュー依頼が来た／修正依頼が付いたとき
    - 前回の状態は `hub/watch_notify.json`（watch*.json は copy-to-workspace / copy-to-home の対象外）
  - 確かめるときは `/api/watch?tickets=14926,14747`（固定の順を使わず判定だけ。記録・通知はしない）
  - /na-go（D）・Docker の順番待ち（E）はまだ無い
- 自動の依頼（2026-11-25〜。B 次のスキル・C 資料の後のコミット・F レビュー）。判定と送信はダッシュボードの同じ常駐ループ（1回に1件。送信は `na_to.py` なので、偶数枠・処理中・入力欄に文字がある枠・本番系の枠には送らない）
  - **`/na-next 番号 [枠] [sweep] [scope] [dry]`**: 止まっている所から次のスキルを頼み、以後そのチケットを自動の依頼の対象にする（固定しただけでは始めない）。枠を指定しなければ空いている Claude の枠（入力待ち・作業中のチケット無し・`/na-slot off` で外していない・他のチケットに割り当てていない）を、設計用の環境3・4 → 環境1・2 の順に選ぶ。1チケット1枠（作業中の枠と違う枠は指定できない）。`dry` は送らずに判定だけ
    - 次のスキル: なし→ct-redmine→ct-analyze→ct-architect→（sweep・scope を付けたら ct-sweep→ct-scope）→ct-planner→ct-issue-docs→コミット
    - 自動で進めるのは ct-redmine の後（→ct-analyze）・ct-sweep／ct-scope の後（→次）・ct-issue-docs の後（→コミット）。**ct-analyze・ct-architect・ct-planner の後は止めて確認待ち**として知らせる（`/na-next 番号` で次へ。architect の後に `sweep`・`scope` を付けて決める）。途中の質問も確認待ち。ct-ship-loop 以降は /na-go（D。未実装）
    - ct-analyze の依頼文には「初期調査はステージング（団体 naga3）・テスティングは団体 nagayoshi・ローカルの DB・Redis が要るときは使う前に質問して止まる」を添える（E ができたら順番待ちに置き換える）
    - コミット（C）は `/ct-commit 番号 issue docs だけをコミット。push しない` を1回だけ
    - 頼まないもの: 次のスキルがすでに動いた記録があるとき（終わったチケットで ct-redmine をコメントに使った等）・ブランチ／PR／03_progress.md があるのに流れの記録が足りないとき（記録の外で進めたチケット）・割り当てた枠と違う枠で作業しているとき
  - レビュー（F）: 固定していないチケットのレビュー依頼・修正依頼は知らせだけ（tmux・Slack DM。「/na-order で順番に入れると ct-pr-turn を自動で頼む」）。**固定したら** `/ct-pr-turn <PR の URL> #番号` を自動で頼む（作業中の枠、無ければ空いている枠。修正依頼は環境1・2の枠だけ）
  - 自動の依頼の失敗（枠が無い・送れない）は tmux と Slack DM で1回だけ知らせる
  - **`/na-slot [off|on 枠…]`**: 自動で割り当てる枠から外す・戻す（例 `/na-slot off 11 12`。`hub/slots.json`）
  - 状態: `hub/autopilot.json`（開始したチケット・割り当てた枠・sweep/scope・処理済みの区切り・送信の記録）。`/na-watch` とダッシュボードの監視欄に「自動 [枠] スキル 送信/失敗 時刻」を出す
  - スキル本体 `hub/skills/na-next`・`na-slot`（hub の `.claude/skills/` からリンク。`.git/info/exclude` 済み）。API は `POST /api/watch/next {ticket, slot, sweep, scope, dry}`
- Claude の枠（奇数枠）への依頼の送付と完了待ち（2026-11-25 決定: hub が送るのは Claude の枠だけ）
  - **ユーザーが送るときは `/na-to <枠番号> <指示>`**（例: `/na-to 3 /ct-redmine 14926`）。hook が送信してプロンプトを止めるので、hub の Claude は動かず hub の会話を消費しない。結果は「UserPromptSubmit operation blocked by hook: na-to ✅ 送信しました …」と画面に出る（"blocked" は正常）。`/na-to 3 /ct-` のように途中で `/` を打つと候補が出る（途中の `/ct-…` は hub では実行されず、文字として送り先に届く）
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

- 開発ダッシュボードに hub を表示するか（今は環境1〜4だけ。hub は環境ではないので登録していない）
- ~~12枠の状態をまとめて出す hub 専用のコマンド・スキルを作るか~~ → 2026-11-25 `hub/bin/hub_status.py` を作成。スキル化はしない（個人用で hub でしか使わず、スキルにするとチーム共有リポへのコミットと全環境への配布になるため。README に書けば hub の Claude は起動時に読む）
