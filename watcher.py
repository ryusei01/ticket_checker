# watcher.py
import json
import time
import argparse
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from notifier import send_line_push, send_line_push_to_all, send_line_broadcast, send_mail_ipv4

def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

def normalize(s):
    # 改行・タブを削除（スペースに変換しない）
    return s.replace("\n", "").replace("\r", "").replace("\t", "").strip()

def check_target(page, target_config, cfg, notified, notification_config=None):
    """単一ターゲットの監視処理"""
    target_name = target_config["name"]
    url = target_config["url"]
    selector = target_config.get("selector", "")
    target_dates = target_config["target_dates"]
    detect_text = target_config.get("detect_text", "")
    # button_selector = target_config.get("button_selector", "")

    found_any = False

    try:
        # 毎回URLに直接アクセス（リロードより確実）
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # セレクタが指定されている場合は待機、なければキーワードで検索
        items = []
        if selector:
            try:
                page.wait_for_selector(selector, timeout=5000)
                items = page.locator(selector).all()
                print(f"[{target_name}] {len(items)}個の要素を検出")
            except PWTimeout:
                print(f"[{target_name}] {selector}が見つかりません。キーワードで要素を検索します。")
                # セレクタが見つからない場合、target_datesを含む要素を全て取得
                items = []
                for td in target_dates:
                    # Playwrightのget_by_textで部分一致検索（正規表現使用）
                    try:
                        # 全要素からテキストで検索
                        matching_elements = page.get_by_text(td, exact=False).all()
                        print(f"[{target_name}] '{td}'を含む要素: {len(matching_elements)}個")
                        items.extend(matching_elements)
                    except Exception as e:
                        print(f"[{target_name}] テキスト検索エラー: {e}")

                if not items:
                    print(f"[{target_name}] キーワードを含む要素が見つかりませんでした")
                    return found_any
        else:
            # selectorが未指定の場合もキーワードで検索
            items = []
            for td in target_dates:
                try:
                    matching_elements = page.get_by_text(td, exact=False).all()
                    items.extend(matching_elements)
                except Exception as e:
                    print(f"[{target_name}] テキスト検索エラー: {e}")

        print(f"[{target_name}] {len(items)}個の要素を処理開始")

        for idx, item in enumerate(items):
            try:
                # innerText を evaluate で確実に取得（タイムアウト付き）
                text = item.evaluate("el => el.innerText || ''", timeout=3000)
                text = normalize(text)

                # 部分一致で各ターゲット日付をチェック
                # スペースを正規化して比較
                normalized_text = ' '.join(text.split())
                for td in target_dates:
                    normalized_td = ' '.join(td.split())

                    if normalized_td in normalized_text:
                        print(f"[{target_name}] 対象枠検出: {td}")

                        # このブロック内にdetect_textが含まれているかチェック
                        # detect_textも正規化して比較
                        normalized_detect = ' '.join(detect_text.split()) if detect_text else ""

                        print(f"[{target_name}] detect_text検索: '{normalized_detect}' in text")

                        if normalized_detect and normalized_detect not in normalized_text:
                            print(f"[{target_name}] ブロック内に'{detect_text}'が見つかりません")
                            print(f"[{target_name}] normalized_text: {normalized_text}")
                            continue

                        print(f"[{target_name}] ブロック内に'{detect_text}'を検出！")

                        # 通知キーの生成
                        notify_key = f"{target_name}||{td}||{detect_text}"

                        # 既に通知済みかチェック
                        if notify_key in notified:
                            print(f"[{target_name}] 既に通知済み（スキップ）: {notify_key}")
                            continue

                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        message = f"[{target_name}] チケット販売を検知しました！\n日付: {td}\n時刻: {now}\n検知文言: {detect_text}\n{url}"

                        # 通知（コマンドラインオプション > config.json の順で優先）
                        if notification_config:
                            # コマンドラインオプションで指定された場合
                            if notification_config.get("broadcast", False):
                                send_line_broadcast(cfg["line_channel_access_token"], message)
                            elif notification_config.get("user_ids"):
                                send_line_push_to_all(cfg["line_channel_access_token"], notification_config["user_ids"], message)
                            else:
                                print("警告: 通知先が指定されていません")
                        else:
                            # config.jsonの設定に従う
                            if cfg.get("use_broadcast", False):
                                send_line_broadcast(cfg["line_channel_access_token"], message)
                            else:
                                # 従来の方法：ユーザーIDリストを使用
                                user_ids = []
                                # line_user_ids（配列）が設定されている場合はそれを使用
                                if "line_user_ids" in cfg and isinstance(cfg["line_user_ids"], list):
                                    user_ids = cfg["line_user_ids"]
                                # line_user_id（単一）が設定されている場合はそれも追加
                                if "line_user_id" in cfg and cfg["line_user_id"]:
                                    if cfg["line_user_id"] not in user_ids:
                                        user_ids.append(cfg["line_user_id"])
                                
                                if user_ids:
                                    send_line_push_to_all(cfg["line_channel_access_token"], user_ids, message)
                                else:
                                    print("警告: 送信先ユーザーIDが設定されていません")
                        
                        send_mail_ipv4(cfg, f"チケット販売検知 [{target_name}]", message)

                        notified.add(notify_key)
                        found_any = True
                        print(f"[{target_name}] 通知完了。キー '{notify_key}' を記録しました。")
                        break  # 1つ見つかったらこの日付のチェック終了

            except Exception as e:
                print(f"[{target_name}] [{idx+1}/{len(items)}] 要素処理エラー: {e}")
                continue

    except Exception as e:
        print(f"[{target_name}] チェック中エラー:", e)

    return found_any

def run_watcher(notification_config=None):
    cfg = load_config()
    chrome_path = cfg["chrome_path"]
    user_data_dir = f'{cfg["user_data_dir"]}\\{cfg["profile"]}'
    interval = cfg["check_interval_sec"]
    stop_after_detection = cfg.get("stop_after_detection", False)
    headless = cfg.get("headless", False)
    watch_targets = cfg.get("watch_targets", [])

    if not watch_targets:
        print("監視対象が設定されていません。config.jsonのwatch_targetsを確認してください。")
        return

    # 既通知をランタイムで管理（再通知防止）
    notified = set()

    print("=== 監視設定 ===")
    for idx, target in enumerate(watch_targets, 1):
        print(f"{idx}. {target['name']}")
        print(f"   URL: {target['url']}")
        print(f"   対象: {target['target_dates']}")
        print(f"   検知ワード: {target.get('detect_text', '')}")
    print("検知後の動作:", "終了" if stop_after_detection else "継続監視")
    print("ブラウザモード:", "Headless（バックグラウンド）" if headless else "表示")
    print("================\n")

    with sync_playwright() as p:
        browser_args = ["--start-maximized"] if not headless else []
        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            executable_path=chrome_path,
            headless=headless,
            args=browser_args
        )

        # 各ターゲット用のタブを作成
        pages = []
        for target in watch_targets:
            page = browser.new_page()
            print(f"[{target['name']}] タブを開いています: {target['url']}")
            page.goto(target['url'], wait_until="networkidle", timeout=30000)
            pages.append(page)

        print("\n全タブの初期ロード完了。監視を開始します。\n")

        while True:
            try:
                found_any = False

                # 各ターゲットを並行チェック（それぞれ専用のタブで）
                for idx, target in enumerate(watch_targets):
                    page = pages[idx]
                    result = check_target(page, target, cfg, notified, notification_config)
                    found_any = found_any or result

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
    parser = argparse.ArgumentParser(
        description="チケット監視スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python watcher.py                           # config.jsonの設定に従う
  python watcher.py --broadcast               # 友達追加した全員に送信
  python watcher.py --user Uxxx               # 特定ユーザーに送信
  python watcher.py --user Uxxx --user Uyyy   # 複数ユーザーに送信
        """
    )
    parser.add_argument(
        "--broadcast",
        action="store_true",
        help="ブロードキャスト送信（友達追加した全員に送信、ユーザーID管理不要）"
    )
    parser.add_argument(
        "--user",
        action="append",
        dest="user_ids",
        help="送信先ユーザーIDを指定（複数指定可能）"
    )
    
    args = parser.parse_args()
    
    # 通知設定を構築
    notification_config = None
    if args.broadcast:
        notification_config = {"broadcast": True}
        print("通知設定: ブロードキャスト送信（友達追加した全員に送信）")
    elif args.user_ids:
        notification_config = {"user_ids": args.user_ids}
        print(f"通知設定: 指定ユーザーに送信 ({len(args.user_ids)}人)")
        for user_id in args.user_ids:
            print(f"  - {user_id}")
    else:
        print("通知設定: config.jsonの設定に従います")
    
    print()
    
    run_watcher(notification_config)
