# チケット監視システム アーキテクチャ解説

## 📋 目次

1. [システム概要](#システム概要)
2. [全体アーキテクチャ](#全体アーキテクチャ)
3. [各コンポーネントの役割](#各コンポーネントの役割)
4. [データフロー](#データフロー)
5. [設定管理](#設定管理)
6. [LINEコマンド一覧](#lineコマンド一覧)
7. [ディレクトリ構成](#ディレクトリ構成)

---

## システム概要

このシステムは、チケット販売サイトを自動監視し、指定したボタンラベル（例: "申込み"）が表示されたらLINEで通知するシステムです。

### 主な特徴

- **Pull型アーキテクチャ**: 家PCは外部公開不要（ポート開放不要）
- **LINE Bot制御**: LINEから監視の開始/停止、設定変更が可能
- **完全無料運用**: AWS・Cloudflare・LINEの無料枠内で動作
- **セキュア**: 家PCは定期的にAWSにアクセスするのみ（外部からアクセス不可）

---

## 全体アーキテクチャ

```
┌─────────────┐
│   LINE Bot  │ ← ユーザーがコマンドを送信
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ Cloudflare Worker   │ ← LINE Webhookを受信
│  (worker.js)        │    コマンドを解析してAWSに転送
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ AWS API Gateway     │
│      +              │
│  Lambda (handler.py)│ ← コマンドをDynamoDBに保存
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│   DynamoDB          │ ← 設定とコマンドを保存
│  (watcher_status)   │
└──────┬──────────────┘
       │
       ▲ (60秒ごとにポーリング)
       │
┌──────┴──────────────┐
│ 家PC                │
│  pull_client.py     │ ← DynamoDBから設定を取得
│       ↓             │
│  watcher.py         │ ← Playwrightで監視実行
└─────────────────────┘
       │
       ▼
   チケット販売サイト
```

---

## 各コンポーネントの役割

### 1. LINE Bot (LINE Messaging API)

**役割**: ユーザーインターフェース

- ユーザーからコマンドを受け取る
- 監視開始/停止、設定変更を受け付ける
- システムの状態をユーザーに通知

**使用するコマンド例**:
```
監視開始
URL設定 https://example.com
日付設定 2025/06/15,2025/06/16
```

---

### 2. Cloudflare Worker (`worker.js`)

**役割**: LINE Webhookハンドラー + コマンド処理

**主な機能**:
- LINE Webhookを受信
- メッセージを解析してコマンドを判定
- AWS APIにコマンドを転送
- LINEへの返信メッセージ送信

**処理フロー**:
```javascript
LINE → handleLineWebhook()
      → handleTextMessage()
         → コマンド判定
            - "URL設定" → AWS API に watch_url を送信
            - "監視開始" → AWS API に start コマンドを送信
            - "設定確認" → AWS API から現在の設定を取得
```

**デプロイ方法**:
```bash
cd cloudflare_worker
wrangler deploy
```

---

### 3. AWS Lambda (`handler.py`)

**役割**: コマンド処理 + 状態管理

**3つのエンドポイント**:

#### 1) `GET /status`
家PCが定期的にポーリング

```python
{
  "watch_status": "start",  # start/stop/status
  "config": {
    "url": "https://example.com",
    "button_label": "申込み",
    "target_dates": ["2025/06/15", "2025/06/16"],
    "notify_user_id": "Uxxxxxxxx"
  }
}
```

#### 2) `POST /command`
Cloudflare Workerからコマンドを受信

```python
# リクエスト
{
  "command": "config",
  "watch_url": "https://example.com",
  "button_label": "申込み",
  "target_dates": ["2025/06/15"]
}

# レスポンス
{
  "success": true,
  "message": "Command saved successfully"
}
```

#### 3) `POST /report`
家PCから現在の状態を受信（オプション）

**デプロイ方法**:
```bash
cd aws_lambda
serverless deploy
```

---

### 4. DynamoDB

**役割**: 設定とコマンドの永続化

**テーブル名**: `ticket-watcher-api-prod`

**データ構造**:
```json
{
  "id": "control",
  "watch_status": "start",
  "watch_url": "https://example.com/tickets",
  "button_label": "申込み",
  "target_dates": ["2025/06/15", "2025/06/16"],
  "notify_user_id": "Uxxxxxxxx",
  "updated_at": "2025-11-28T12:34:56",
  "message": "監視開始"
}
```

---

### 5. 家PC - Pull Client (`pull_client.py`)

**役割**: AWS APIをポーリングして監視プロセスを制御

**動作フロー**:
```
1. 60秒ごとにAWS API Gateway (/status) にアクセス
2. watch_status を確認
   - "start" → watcher.py を起動
   - "stop"  → watcher.py を停止
3. 設定情報を watcher.py に渡す
```

**主なメソッド**:
```python
class WatcherController:
    def start_watch():     # 監視開始
    def stop_watch():      # 監視停止
    def is_running():      # 監視中か確認
    def fetch_command_from_aws():  # AWSから設定取得
```

**起動方法**:
```bash
python pull_client.py
```

---

### 6. 監視スクリプト (`watcher.py`)

**役割**: Playwrightでチケットサイトを監視

**動作フロー**:
```python
1. config.json を読み込み
2. Playwright でブラウザ起動
3. target_url にアクセス
4. target_dates の td 要素を探す
5. button_label のボタンを探す
6. 見つかったら LINE に通知
7. 10秒待機して繰り返し
```

**重要な機能**:
- **重複通知防止**: `notified` セットで通知済みを管理
- **ラベル変化検知**: `last_button_labels` で前回のラベルを記憶
  - "受付は終了しました" → "申込み" の変化を検知

**通知の仕組み**:
```python
# 初回検知
"2025/06/15||申込み" → 通知 ✅

# 同じ状態（スキップ）
"2025/06/15||申込み" → スキップ ❌

# ラベル変化（再通知）
"2025/06/15||受付は終了しました" → "2025/06/15||申込み" → 再通知 ✅
```

---

## データフロー

### 監視開始の流れ

```
1. ユーザー: LINE で「監視開始」と送信
   ↓
2. LINE: Cloudflare Worker に Webhook 送信
   ↓
3. Cloudflare Worker:
   - メッセージを解析
   - AWS API Gateway に POST /command
     {command: "start"}
   ↓
4. Lambda:
   - DynamoDB に保存
     {id: "control", watch_status: "start"}
   ↓
5. 家PC (pull_client.py):
   - 60秒後にポーリング
   - GET /status で watch_status="start" を取得
   - watcher.py を起動
   ↓
6. watcher.py:
   - チケットサイトを監視開始
   - ボタンを検知したら LINE に通知
```

### 設定変更の流れ

```
1. ユーザー: LINE で「URL設定 https://example.com」と送信
   ↓
2. Cloudflare Worker:
   - "URL設定" を検知
   - AWS に POST /command
     {command: "config", watch_url: "https://example.com"}
   ↓
3. Lambda:
   - 既存の設定を DynamoDB から取得
   - watch_url のみ更新して保存
   ↓
4. 家PC:
   - 次回ポーリング時に新しい設定を取得
   - 監視中なら watcher.py に反映
```

---

## 設定管理

### config.json (ローカル設定)

```json
{
  "target_url": "http://localhost:3000",
  "target_dates": ["2025/06/15", "2025/06/16"],
  "line_notify_token": "YOUR_LINE_NOTIFY_TOKEN",
  "check_interval": 10,
  "headless": true,
  "button_label": "申込み",
  "stop_after_detection": false
}
```

### DynamoDB (リモート設定)

LINEから設定すると DynamoDB に保存され、家PCが取得します。

**設定項目**:
- `watch_url`: 監視するURL
- `button_label`: 検知するボタンのラベル
- `target_dates`: 対象日付の配列
- `notify_user_id`: LINE通知先ユーザーID

---

## LINEコマンド一覧

### 基本操作

| コマンド | 説明 | 例 |
|---------|------|-----|
| `監視開始` | 監視を開始 | `監視開始` |
| `監視停止` | 監視を停止 | `監視停止` |
| `状態` | 現在の状態確認 | `状態` |

### 設定変更

| コマンド | 説明 | 例 |
|---------|------|-----|
| `URL設定 <URL>` | 監視URLを設定 | `URL設定 https://example.com` |
| `ラベル設定 <ラベル>` | ボタンラベルを設定 | `ラベル設定 申込み` |
| `日付設定 <日付>` | 対象日付を設定 | `日付設定 2025/06/15,2025/06/16` |
| `通知先設定 <UserID>` | 通知先を設定 | `通知先設定 Uxxxxxxxx` |
| `設定確認` | 現在の設定を表示 | `設定確認` |

### ヘルプ

コマンド以外のメッセージを送信すると、使い方が表示されます。

---

## ディレクトリ構成

```
ticket_checker/
│
├── watcher.py              # メイン監視スクリプト
├── pull_client.py          # Pull型クライアント（家PC）
├── config.json             # ローカル設定ファイル
│
├── aws_lambda/             # AWS Lambda関数
│   ├── handler.py          # Lambda関数本体
│   └── serverless.yml      # Serverless Framework設定
│
├── cloudflare_worker/      # Cloudflare Worker
│   ├── worker.js           # Worker本体
│   └── wrangler.toml       # Wrangler設定
│
├── frontend/               # テスト用フロントエンド
│   └── ticket-checker/     # Next.js アプリ
│       ├── app/
│       │   ├── page.tsx           # トップページ
│       │   ├── entry/page.tsx     # 席選択ページ
│       │   ├── payment/page.tsx   # 支払い方法ページ
│       │   └── confirm/page.tsx   # 確認ページ
│       └── package.json
│
├── logs/                   # ログファイル（自動生成）
├── watcher.pid             # 監視プロセスID（自動生成）
│
├── SETUP_GUIDE.md          # セットアップガイド
├── ARCHITECTURE.md         # このファイル（アーキテクチャ解説）
└── README.md               # プロジェクト概要
```

---

## セキュリティ

### Pull型のメリット

- **ポート開放不要**: 家PCは外部からアクセス不可
- **NAT越え不要**: 外向きHTTPSのみ
- **ngrok/Tunnel不要**: 外部公開の必要なし
- **ファイアウォール通過**: 通常のHTTPS通信のみ

### 認証情報の管理

**機密情報**:
- LINE Channel Secret
- LINE Channel Access Token
- AWS Access Key / Secret Key

**保存場所**:
- Cloudflare Worker: 環境変数またはコード内
- AWS: IAM ユーザー認証情報
- 家PC: config.json（LINE Notify Token）

**注意**:
- これらの情報は `.gitignore` に追加してGitにコミットしないこと
- 本番環境では環境変数で管理推奨

---

## トラブルシューティング

### LINEコマンドが反応しない

1. Cloudflare Worker のログ確認: `wrangler tail`
2. AWS Lambda のログ確認: CloudWatch Logs
3. DynamoDB のデータ確認: AWS Console

### 家PCで状態変化が反映されない

1. `pull_client.py` の API_URL 確認
2. ネットワーク接続確認
3. AWS API Gateway の CORS 設定確認

### 監視が開始/停止しない

1. `watcher.py` のパス確認
2. `config.json` の設定確認
3. PIDファイル (`watcher.pid`) の削除を試す

---

## 今後の拡張案

- [ ] 複数ユーザー対応
- [ ] 監視対象の動的変更（複数URL）
- [ ] 検知履歴の保存・表示
- [ ] Webダッシュボード
- [ ] スケジュール監視（特定時間のみ監視）
- [ ] 通知テンプレートのカスタマイズ
- [ ] リッチメッセージ対応（Flex Message）

---

## ライセンス

このプロジェクトは個人利用を目的としています。

## 作成日

2025年11月28日
