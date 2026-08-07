# 🚇 Tokyo Metro Alert (TMA)

東京メトロの列車が指定した駅に接近すると、画面と音でお知らせするWebアプリです。

> 旧名称: TOYOCHO ALERT(東西線専用だった時代の名称。全10路線対応・マルチユーザー化に伴い改名)

## 機能

- **東京メトロ全10路線対応**(銀座線・丸ノ内線・丸ノ内線支線・日比谷線・東西線・千代田線・有楽町線・半蔵門線・南北線・副都心線)
- 駅・行先・列番を指定した接近監視(行先・列番は省略可)
- 全画面アラーム+アラーム音による通知
- 通知履歴・統計(今日/累計)の表示
- **マルチユーザー対応**: Cookieによる匿名識別で、監視・アラーム・履歴・統計は利用者ごとに完全分離
- サーバー再起動時の監視自動復元(SQLite保存)

データソース: [nkth.info](https://nkth.info/) の在線情報API(ODPTデータ)

## 起動方法(ローカル)

初回セットアップ:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

起動(どちらでも):

- `start.bat` をダブルクリック(ブラウザも自動で開きます)
- または `.venv\Scripts\python.exe app.py` → http://127.0.0.1:5000/

※ ブラウザの自動再生制限のため、ページを開いたら一度クリックして音を有効化してください(画面下部の案内が消えればOK)。

## テスト

```
.venv\Scripts\python.exe -m pytest tests/
```

## 公開(Render等)する場合

- Start Command: `gunicorn --workers 1 --threads 8 app:app`
  (監視状態はプロセス内メモリのため **workers は必ず 1**)
- SQLite(`data/toyotyo.db`)は再デプロイで消える環境があるため、履歴を永続させる場合は Persistent Disk を `data/` にマウントしてください
- タイムスタンプはコード側でJST固定のため `TZ` の設定は不要です

## 路線・行先の追加

コード変更は不要です。[data/lines.json](data/lines.json) にエントリを追記してください
(駅名・行先名はAPIのODPT表記と完全一致させること)。

## 構成

| ファイル | 役割 |
|---|---|
| `app.py` | Flaskエンドポイント・利用者識別(Cookie) |
| `monitor.py` | 監視スレッド(TrainMonitor)・利用者別管理(MonitorManager)・路線APIキャッシュ |
| `db.py` | SQLite層(利用者・履歴・監視状態) |
| `lines.py` / `data/lines.json` | 路線マスタデータ |
| `timeutil.py` | JST日時ユーティリティ |
| `templates/` `static/` | 画面 |
| `tests/` | pytest テスト |

## 環境変数

| 変数 | 既定値 | 説明 |
|---|---|---|
| `PORT` | 5000 | 待受ポート |
| `FLASK_DEBUG` | 0 | 1で開発モード |
| `MAX_MONITORS` | 50 | 全体の同時監視数上限 |
| `MAX_MONITOR_HOURS` | 12 | 連続監視の上限(超過で自動終了) |
