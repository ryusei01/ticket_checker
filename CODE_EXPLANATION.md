# チケット監視システム - コード解説

## 概要

このシステムは、複数のチケット販売サイトを自動監視し、特定の条件に一致したときに通知・自動クリックを行う Python 製の監視ツールです。

---

## ファイル構成

```
ticket_checker/
├── watcher.py              # メイン監視スクリプト
├── notifier.py             # LINE/メール通知機能
├── pull_client.py          # AWS Lambda連携クライアント
├── config.json             # 監視設定ファイル
├── aws_lambda/             # AWS Lambda関数
│   └── handler.py          # LINEコマンド処理
├── cloudflare_worker/      # Cloudflare Worker
│   └── worker.js           # LINEウェブフック処理
└── frontend/               # Next.js テストページ
```

---

## 主要コンポーネント

### 1. watcher.py - メイン監視スクリプト

#### 基本構造

```python
def run_watcher():
    # 設定読み込み
    cfg = load_config()

    # Playwrightでブラウザ起動
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(...)

        # 各監視対象用のタブを開く
        pages = []
        for target in watch_targets:
            page = browser.new_page()
            page.goto(target['url'])
            pages.append(page)

        # 監視ループ
        while True:
            for idx, target in enumerate(watch_targets):
                page = pages[idx]
                check_target(page, target, cfg, notified)

            time.sleep(interval)
```

**ポイント:**

- **Playwright**: ヘッドレスブラウザ自動化ライブラリ
- **タブごとに監視**: 各サイトを別タブで開き、並行監視
- **無限ループ**: `while True`で常時監視

#### check_target() - 監視処理の詳細

```python
def check_target(page, target_config, cfg, notified):
    # 1. ページリロード
    page.reload(wait_until="networkidle")

    # 2. 要素の検出
    if selector:
        items = page.locator(selector).all()  # CSSセレクタで取得
    else:
        # セレクタがない場合はキーワード検索
        items = page.get_by_text(td, exact=False).all()

    # 3. 各要素のチェック
    for item in items:
        text = item.evaluate("el => el.innerText || ''")
        text = normalize(text)

        # 4. 条件マッチング
        if target_dates in text and detect_text in text:
            # 5. 通知
            send_line_push(...)
            send_mail_ipv4(...)

            # 6. ボタンクリック
            btn = item.locator(button_selector).first
            btn.click()
```

**処理フロー:**

1. **ページリロード**: `wait_until="networkidle"`で JavaScript 実行完了を待つ
2. **要素検出**:
   - CSS セレクタ（例: `ul.table_data`）で要素を取得
   - セレクタが見つからない場合は`get_by_text()`でフォールバック
3. **テキスト取得**: `evaluate()`で JavaScript を実行し`innerText`を取得
4. **正規化**: 改行・タブを削除、スペースを正規化
5. **条件判定**:
   - `target_dates`（日付キーワード）が含まれているか
   - `detect_text`（検知ワード）が含まれているか
6. **通知とクリック**: 条件に一致したら LINE/メール送信 + ボタンクリック

#### normalize() - テキスト正規化

```python
def normalize(s):
    # 改行・タブを削除（スペースに変換しない）
    return s.replace("\n", "").replace("\r", "").replace("\t", "").strip()
```

**目的:**

- HTML 内の改行やタブを削除
- 文字列比較を容易にする

**例:**

```
入力: "予定枚\n数終了"
出力: "予定枚数終了"
```

---

### 2. config.json - 設定ファイル

```json
{
  "chrome_path": "...",
  "headless": false,
  "check_interval_sec": 3,
  "watch_targets": [
    {
      "name": "ぴあ - B'z検索",
      "url": "https://...",
      "selector": "ul.table_data",
      "target_dates": ["直前販売(東京公演)＜12/7＞"],
      "detect_text": "販売期間中",
      "button_selector": ".btn_detail"
    }
  ]
}
```

**主要パラメータ:**

| パラメータ           | 説明                   | 例                                |
| -------------------- | ---------------------- | --------------------------------- |
| `chrome_path`        | Chrome の実行パス      | `C:\Program Files\...\chrome.exe` |
| `headless`           | バックグラウンド実行   | `true`/`false`                    |
| `check_interval_sec` | チェック間隔（秒）     | `3`                               |
| `selector`           | 要素の CSS セレクタ    | `ul.table_data`                   |
| `target_dates`       | 検知する日付キーワード | `["東京公演＜12/7＞"]`            |
| `detect_text`        | 検知する文言           | `"販売期間中"`                    |
| `button_selector`    | クリックするボタン     | `.btn_detail`                     |

---

### 3. Playwright の仕組み

#### launch_persistent_context()

```python
browser = p.chromium.launch_persistent_context(
    user_data_dir=user_data_dir,      # プロファイル保存場所
    executable_path=chrome_path,      # Chrome実行パス
    headless=headless,                # ヘッドレスモード
    args=["--start-maximized"]        # 起動オプション
)
```

**persistent_context とは:**

- 通常のブラウザと同じように Cookie やログイン状態を保持
- セッション情報を`user_data_dir`に保存
- 再起動してもログイン状態が維持される

**headless モード:**

- `headless=True`: ブラウザウィンドウを表示せず、バックグラウンドで実行
- `headless=False`: 通常のブラウザウィンドウを表示

#### Locator API

```python
# CSSセレクタで要素を取得
items = page.locator("ul.table_data").all()

# テキストで要素を検索
items = page.get_by_text("東京公演", exact=False).all()

# JavaScriptを実行してテキスト取得
text = item.evaluate("el => el.innerText || ''")

# ボタンをクリック
btn = item.locator(".btn_detail").first
btn.click()
```

---

### 4. 通知機能

#### LINE 通知 (notifier.py)

```python
def send_line_push(access_token, user_id, message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}]
    }
    requests.post(url, headers=headers, json=data)
```

**LINE Messaging API:**

- プッシュメッセージでユーザーに通知
- `access_token`: LINE Developers で取得
- `user_id`: 通知先のユーザー ID

#### メール通知

```python
def send_mail_ipv4(cfg, subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["smtp_user"]
    msg["To"] = cfg["mail_to"]

    with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"]) as server:
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.send_message(msg)
```

---

### 5. AWS Lambda 連携（pull_client.py）

#### Pull 型アーキテクチャ

```python
def poll_status():
    while True:
        # AWS Lambdaから状態を取得
        response = requests.get(API_URL, headers=headers)
        data = response.json()

        if data["command"] == "start":
            # watcher.pyを起動
            subprocess.Popen(["python", "watcher.py"])
        elif data["command"] == "stop":
            # watcher.pyを停止
            kill_watcher()

        time.sleep(60)  # 60秒ごとにポーリング
```

**仕組み:**

1. 60 秒ごとに Lambda の API をチェック
2. LINE からのコマンド（開始/停止）を取得
3. ローカルで watcher.py プロセスを制御

**Pull 型の利点:**

- 自宅 PC へのポート開放不要
- ファイアウォール越しでも動作
- セキュリティリスクが低い

---

## 監視フローの全体像

```
1. ブラウザ起動
   ↓
2. 各監視対象のタブを開く
   ├─ タブ1: ぴあ
   └─ タブ2: B'z公式
   ↓
3. ループ開始
   ├─ タブ1をリロード
   │  ├─ ul.table_data 要素を検出
   │  ├─ 各要素のテキストを取得
   │  ├─ "直前販売(東京公演)＜12/7＞" を含むか？
   │  └─ "販売期間中" を含むか？
   │      └─ YES → 通知 + クリック
   │
   ├─ タブ2をリロード
   │  └─ （同様の処理）
   │
   └─ 3秒待機 → ループ継続
```

---

## よくある問題と解決策

### 1. セレクタが見つからない

**問題:** `[サイト名] ul.table_data が見つかりません`

**原因:**

- ページ構造が変わった
- JavaScript の読み込みが遅い

**解決策:**

```python
# セレクタのタイムアウトを延長
page.wait_for_selector(selector, timeout=10000)

# または、キーワード検索にフォールバック（自動実装済み）
items = page.get_by_text(td, exact=False).all()
```

### 2. テキストが一致しない

**問題:** プレビューにはテキストがあるのに検知されない

**原因:**

- 文字コードの違い（`'` vs `'`）
- 改行やスペースの位置

**解決策:**

```python
# より短いキーワードを使用
"target_dates": ["東京公演＜12/7＞"]  # 短く確実な部分のみ

# スペース正規化（実装済み）
normalized_text = ' '.join(text.split())
```

### 3. 重複通知

**問題:** 同じ検知で何度も通知が来る

**原因:**

- 通知済み管理が機能していない

**解決策:**

```python
# 通知キーで管理（実装済み）
notify_key = f"{target_name}||{td}||{detect_text}"
if notify_key in notified:
    continue
notified.add(notify_key)
```

---

## パフォーマンス最適化

### タイムアウト設定

```python
# ページロード
page.goto(url, wait_until="networkidle", timeout=30000)

# 要素検出
page.wait_for_selector(selector, timeout=5000)

# テキスト取得
text = item.evaluate("el => el.innerText || ''", timeout=3000)
```

### 並行処理

現在は**順次処理**（1 つずつチェック）:

```python
for target in watch_targets:
    check_target(page, target, ...)
```

将来的に**並行処理**に変更可能（複数タブを同時にリロード）

---

## セキュリティ考慮事項

1. **認証情報の保護**

   - `config.json`は`.gitignore`に追加
   - 環境変数での管理を推奨

2. **Pull 型アーキテクチャ**

   - 自宅 PC がサーバーにならない
   - ポート開放不要

3. **ログイン状態の管理**
   - `user_data_dir`で Cookie を永続化
   - 定期的に手動ログインが必要な場合あり

---

## 拡張案

### 1. 複数条件の OR/AND

現在: `target_dates` AND `detect_text`

拡張:

```json
"conditions": {
  "logic": "OR",
  "rules": [
    {"target": "東京公演", "detect": "販売中"},
    {"target": "大阪公演", "detect": "受付中"}
  ]
}
```

### 2. スクリーンショット保存

```python
if found:
    page.screenshot(path=f"detection_{now}.png")
```

### 3. Webhook 通知

LINE 以外の通知先（Slack, Discord）にも対応

---

## まとめ

このシステムは以下の技術を組み合わせています:

- **Playwright**: ブラウザ自動化
- **Pull 型ポーリング**: AWS Lambda 連携
- **LINE Messaging API**: 通知
- **正規化とパターンマッチング**: 柔軟なテキスト検知

監視対象の追加は`config.json`の`watch_targets`配列に追加するだけで可能です。
