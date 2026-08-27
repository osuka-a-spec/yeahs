# 移転企業チェック(東京23区・場所×人数タグ) — GitHub Actions版

Googleニュースのニュース検索(RSS)を使って、東京23区内の企業移転ニュースを1時間ごとに自動チェックし、
場所(建物名 > エリア名 > 区名 > 23区)と従業員数の組み合わせタグを付けてメールで通知します。

Claude(Cowork)のスケジュールタスクと違い、これは完全にGitHub側のサーバーで動くので、
誰かがログインしたり画面を開いたりする必要は一切ありません。

## 中身

- `check_relocations.py` — 本体のスクリプト(標準ライブラリのみ、追加インストール不要)
- `.github/workflows/hourly_check.yml` — 毎時1分に自動実行する設定
- `seen.json` — 一度通知した記事を記録しておくファイル(重複通知を防ぐため、実行のたびに自動更新される)

## セットアップ手順

### 1. GitHubアカウントを作る(すでにあれば不要)
https://github.com/ にアクセスし、無料アカウントを作成します。

### 2. 新しいリポジトリを作る
GitHub右上の「+」→「New repository」を選び、名前を決めて(例: `relocation-checker`)、
「Private」を選んで作成します(社内の検索条件が含まれるため公開しないことを推奨します)。

### 3. このフォルダの中身をアップロードする
作成したリポジトリの画面で「Add file」→「Upload files」を選び、
このフォルダの中身(`check_relocations.py`、`.github`フォルダごと、`seen.json`、`README.md`)を
すべてドラッグ&ドロップしてアップロードし、「Commit changes」を押します。
`.github/workflows/hourly_check.yml` のフォルダ構造は崩さずにそのままアップロードしてください。

### 4. Gmailの「アプリパスワード」を発行する
通常のGmailログインパスワードはここでは使えません。専用の「アプリパスワード」が必要です。

1. 通知に使うGmailアカウントで、2段階認証を有効にする(まだの場合)
   https://myaccount.google.com/security
2. https://myaccount.google.com/apppasswords にアクセスし、
   アプリ名を適当に入力して(例: `relocation-checker`)、パスワードを発行する
3. 表示される16桁のパスワード(スペースなし)をコピーしておく
   ※このパスワードは後で使うのでメモしておいてください。二度と表示されません。

### 5. リポジトリにSecrets(秘密情報)を登録する
アップロードしたリポジトリの「Settings」タブ →「Secrets and variables」→「Actions」を開き、
「New repository secret」で以下の3つを登録します。

| Name | Value |
|---|---|
| `GMAIL_ADDRESS` | 送信元のGmailアドレス(例: yourname@gmail.com) |
| `GMAIL_APP_PASSWORD` | 手順4で発行した16桁のアプリパスワード |
| `TO_EMAIL` | 通知を受け取りたいメールアドレス(osuka-a@ymedical.jp) |

### 6. Actionsを有効にする
リポジトリの「Actions」タブを開き、案内に従って有効化します
(「I understand my workflows, go ahead and enable them」のようなボタンが出たら押してください)。

### 7. 動作確認する
「Actions」タブ →「移転企業チェック(東京23区)」というワークフローを選び、
右側の「Run workflow」ボタンを押すと、スケジュールを待たずに今すぐ1回実行できます。
数十秒〜1分程度で完了し、ログに結果が表示されます。うまくいけばメールが届きます。

これで設定完了です。あとは毎時1分に自動的にチェックが走り続けます。

## 運用メモ

- 動作確認期間は「0件でも実行報告メールを送る」設定(`REPORT_ON_ZERO: 'true'`)になっています。
  しばらく様子を見て問題なければ、`.github/workflows/hourly_check.yml` の中の
  `REPORT_ON_ZERO: 'true'` を `REPORT_ON_ZERO: 'false'` に変更してください(0件時は送信されなくなります)。
- GitHub Actionsの無料枠のスケジュール実行は、混雑状況によって指定時刻から数分〜十数分遅れることがあります。
- 従業員数や住所の抽出はニュース記事のテキストから自動で読み取る簡易的な仕組みのため、
  取得できないケースもあります(その場合は「不明」として扱われます)。
- 場所タグの対象(建物名・エリア名・区名)や、従業員数の区切り(50/100/300名)を変えたい場合は、
  `check_relocations.py` の上の方にある `BUILDINGS` / `AREAS` / `PRIORITY_WARDS` の一覧や
  `headcount_label()` の数字を書き換えて、再度アップロードしてください。
