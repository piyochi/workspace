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
  - tmuxp を読み込んだ直後は1番の枠が MAIN の位置に表示されている。番号無しの枠に戻すには、表示中の番号（Alt+1）をもう一度押す
- 枠番号とペイン ID（`%NN`）の対応はフォーカス切り替えのたびに変わる。**送る直前に毎回 `tmux_link.py list` で引き直す**

## hub がやること・やらないこと

やること:
- 12枠の一覧と状態（実行中・入力待ち・空き）、各枠のチケット番号・段階の把握（`tmux_link.py list`・枠タイトル・開発ダッシュボードの「対応中」）
  - **ユーザーが見るときは `/na-list`**: Claude の枠（奇数枠）だけを1枠2行（状態・チケット・ブランチ・会話量・完了時刻／最後の応答の末尾）で画面に出す。`/na-to` と同じ hook（`na_to.py --hook`）が表示してプロンプトを止めるので、hub の会話を消費しない。スキル本体 `hub/skills/na-list/SKILL.md` を hub の `.claude/skills/na-list` からシンボリックリンク（`.git/info/exclude` 済み）
  - hub の Claude が見るときは `python3 ~/.local/share/ticket-v2/hub/bin/hub_status.py`（12枠を1行ずつ要約。--active で起動中だけ、--compact で /na-list と同じ形）。詳しく見る枠だけ `tmux_link.py read %ID`
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
