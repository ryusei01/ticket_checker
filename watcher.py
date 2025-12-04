# watcher.py
import json
import time
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from notifier import send_line_push, send_mail_ipv4

def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

def normalize(s):
    return s.replace("\n", " ").replace("\r", " ").strip()

def run_watcher():
    cfg = load_config()
    chrome_path = cfg["chrome_path"]
    user_data_dir = f'{cfg["user_data_dir"]}\\{cfg["profile"]}'
    url = cfg["target_url"]
    target_dates = cfg["target_dates"]
    interval = cfg["check_interval_sec"]
    button_text = cfg["button_text"]
    stop_after_detection = cfg.get("stop_after_detection", False)
    headless = cfg.get("headless", False)

    # 既通知をランタイムで管理（再通知防止）
    notified = set()
    # 各日付の最後に検知したボタンラベルを記録
    last_button_labels = {}

    print("監視対象日時:", target_dates)
    print("検知後の動作:", "終了" if stop_after_detection else "継続監視")
    print("ブラウザモード:", "Headless（バックグラウンド）" if headless else "表示")
    with sync_playwright() as p:
        browser_args = ["--start-maximized"] if not headless else []
        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            executable_path=chrome_path,
            headless=headless,
            args=browser_args
        )
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        while True:
            try:
                page.reload(wait_until="networkidle")
                # tpl-reception-item が描画されるまで待つ（最大10秒）
                try:
                    page.wait_for_selector("tpl-reception-item", timeout=10000)
                except PWTimeout:
                    print("tpl-reception-itemが見つかりません（タイムアウト）。再試行します。")
                    time.sleep(interval)
                    continue

                # 全アイテムを取得
                items = page.locator("tpl-reception-item").all()
                found_any = False

                for item in items:
                    # innerText を evaluate で確実に取得
                    text = item.evaluate("el => el.innerText || ''")
                    text = normalize(text)
                    # 部分一致で各ターゲット日付をチェック
                    for td in target_dates:
                        if td in text:
                            print(f"対象枠検出: {td}")
                            # ボタンを探す（reception-action 内）
                            # button 要素内の .text-area を読む
                            button_locator = item.locator(".reception-action button")
                            if button_locator.count() == 0:
                                print("ボタンが見つかりません（まだ非表示？）")
                                continue
                            btn = button_locator.first
                            # text-area を確実に読む
                            try:
                                label = btn.locator(".text-area").inner_text().strip()
                            except Exception:
                                label = btn.inner_text().strip()
                            print("ボタンラベル:", label)
                            if button_text in label:
                                # 前回のボタンラベルをチェック
                                last_label = last_button_labels.get(td)

                                # ボタンラベルが変わったかどうかをチェック
                                label_changed = (last_label is not None and last_label != label)

                                # 重複通知防止キー（日付とボタンラベルの組み合わせで管理）
                                key = f"{td}||{label}"

                                if key in notified and not label_changed:
                                    print("既に通知済み（スキップ）:", key)
                                    continue

                                # ラベルが変わった場合は通知済みキーから削除して再通知
                                if label_changed:
                                    print(f"ボタンラベルが変更されました: '{last_label}' → '{label}'")
                                    # 古いキーを削除
                                    old_key = f"{td}||{last_label}"
                                    notified.discard(old_key)

                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                message = f"チケット販売を検知しました！\n日付: {td}\n時刻: {now}\nボタン: {label}\n{url}"
                                # 通知
                                send_line_push(cfg["line_channel_access_token"], cfg["line_user_id"], message)
                                send_mail_ipv4(cfg, "チケット販売検知", message)
                                # クリック
                                try:
                                    btn.click()
                                    print("自動クリック実行")
                                except Exception as e:
                                    print("クリック失敗:", e)

                                notified.add(key)
                                last_button_labels[td] = label
                                found_any = True
                                print(f"通知完了。キー '{key}' を記録しました。")
                            else:
                                print("ボタンはあるが条件に合致しない:", label)
                                # 条件に合致しないボタンも記録しておく（ラベル変更検知のため）
                                last_button_labels[td] = label

                if found_any:
                    print("検知処理済み。")
                    if stop_after_detection:
                        print("stop_after_detection=true のため終了します。")
                        break
                    else:
                        print("継続監視します。次ループまで待機します。")
                        time.sleep(interval)
                        continue

                print(f"{datetime.now():%H:%M:%S} - 未検出。{interval}s後再試行。")
                time.sleep(interval)

            except Exception as e:
                print("監視ループ例外:", e)
                time.sleep(interval)

        browser.close()

if __name__ == "__main__":
    run_watcher()
