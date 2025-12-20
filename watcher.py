# watcher.py
import json
import time
import argparse
import unicodedata
from datetime import datetime
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from notifier import send_notifications_async

def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

def normalize(s):
    # 改行・タブを削除（スペースに変換しない）
    return s.replace("\n", "").replace("\r", "").replace("\t", "").strip()

def normalize_alphabet(s):
    """全角英数字を半角に変換"""
    if not s:
        return s
    # 全角英数字を半角に変換
    result = ""
    for char in s:
        # 全角英数字（Ａ-Ｚ、ａ-ｚ、０-９）を半角に変換
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:  # 全角英数字・記号の範囲
            result += unicodedata.normalize('NFKC', char)
        else:
            result += char
    return result

def check_target(page, target_config, cfg, notified, notification_config=None):
    """単一ターゲットの監視処理
    戻り値: (検知したかどうか, 検知した要素のリンクのリスト)
    """
    target_name = target_config["name"]
    url = target_config["url"]
    selector = target_config.get("selector", "")
    target_dates = target_config["target_dates"]
    detect_text = target_config.get("detect_text", "")
    # button_selector = target_config.get("button_selector", "")
    enable_detail_watch = target_config.get("enable_detail_watch", False)
    detail_seat_types = target_config.get("detail_seat_types", [])  # 席種指定（詳細ページ用）
    # 詳細ページかどうか（ターゲット単位で固定）
    is_detail_page_target = "詳細" in target_name

    found_any = False
    detected_links = []  # 検知した要素のリンクを保存

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
                    return found_any, detected_links
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
                # 席種情報を取得（詳細ページ用、常に取得を試みる）
                seat_type = None
                try:
                    # valiationの値を取得
                    valiation_input = item.locator('input.valiation').first
                    if valiation_input.count() > 0:
                        seat_type = valiation_input.get_attribute('value')
                    else:
                        # ticketSelect__textから席種名を抽出
                        text_elem = item.locator('.ticketSelect__text').first
                        if text_elem.count() > 0:
                            text_content = text_elem.inner_text()
                            # 「Ａ席 7,000円」から「Ａ席」を抽出（最初のスペースまで）
                            if ' ' in text_content:
                                seat_type = text_content.split(' ')[0]
                            else:
                                seat_type = text_content
                except Exception as e:
                    # 席種情報が取得できない場合（親ページなど）はスキップ
                    pass
                
                # 席種指定がある場合、席種の一致チェックを行う
                if detail_seat_types and seat_type:
                    seat_matched = False
                    # 席種を正規化（全角英数字を半角に変換）
                    normalized_seat_type = normalize_alphabet(seat_type)
                    for seat_pattern in detail_seat_types:
                        # パターンも正規化
                        normalized_pattern = normalize_alphabet(seat_pattern)
                        # 部分一致でチェック（「Ｓ席」で「注釈付きＳ席」も検知、全角・半角を考慮）
                        if normalized_pattern in normalized_seat_type or normalized_seat_type in normalized_pattern:
                            seat_matched = True
                            print(f"[{target_name}] 席種一致: '{seat_type}' (パターン: '{seat_pattern}')")
                            break
                    
                    if not seat_matched:
                        print(f"[{target_name}] 席種不一致: '{seat_type}' (指定席種: {detail_seat_types})")
                        continue

                # innerText を evaluate で確実に取得（タイムアウト付き）
                text = item.evaluate("el => el.innerText || ''", timeout=3000)
                text = normalize(text)

                # 部分一致で各ターゲット日付をチェック
                # スペースを正規化して比較
                normalized_text = ' '.join(text.split())
                
                # 詳細ページ（席種フィルタを使っている場合）は、座席ブロック内に日付が無いことが多いので日付チェックをスキップ
                # それ以外は、従来通り target_dates が空のときだけスキップ
                date_matched = (is_detail_page_target and bool(detail_seat_types)) or (len(target_dates) == 0)
                matched_date = ""
                
                for td in target_dates:
                    normalized_td = ' '.join(td.split())

                    if normalized_td in normalized_text:
                        print(f"[{target_name}] 対象枠検出: {td}")
                        date_matched = True
                        matched_date = td
                        break
                
                if not date_matched:
                    continue

                # このブロック内にdetect_textが含まれているかチェック
                # detect_textも正規化して比較
                normalized_detect = ' '.join(detect_text.split()) if detect_text else ""

                print(f"[{target_name}] detect_text検索: '{normalized_detect}' in text")

                if normalized_detect and normalized_detect not in normalized_text:
                    print(f"[{target_name}] ブロック内に'{detect_text}'が見つかりません")
                    print(f"[{target_name}] normalized_text: {normalized_text}")
                    continue

                print(f"[{target_name}] ブロック内に'{detect_text}'を検出！")

                # 詳細ページかどうか（通知メッセージ・通知キー用）
                is_detail_page = is_detail_page_target
                
                # 通知キーの生成（親ページと詳細ページで完全に分離）
                # target_nameとURLを含めることで、親ページと詳細ページで確実に異なる通知キーになる
                if is_detail_page:
                    # 詳細ページ: target_name、URL、席種情報を含める
                    seat_info = f"席種:{seat_type}" if seat_type else ""
                    notify_key = f"詳細||{target_name}||{url}||{matched_date}||{detect_text}||{seat_info}"
                else:
                    # 親ページ: target_name、URLを含める（席種情報は含めない）
                    notify_key = f"親||{target_name}||{url}||{matched_date}||{detect_text}||"

                # 既に通知済みかチェック
                if notify_key in notified:
                    print(f"[{target_name}] 既に通知済み（スキップ）: {notify_key}")
                    continue

                # 詳細ページ監視が有効な場合、リンクを取得
                detail_link = None
                if enable_detail_watch:
                    try:
                        # 要素内の最初の<a>タグのhrefを取得
                        link_element = item.locator('a').first
                        if link_element.count() > 0:
                            detail_link = link_element.get_attribute('href')
                            # 相対URLの場合は絶対URLに変換
                            if detail_link and not detail_link.startswith('http'):
                                detail_link = urljoin(url, detail_link)
                            print(f"[{target_name}] 詳細ページリンクを取得: {detail_link}")
                    except Exception as e:
                        print(f"[{target_name}] リンク取得エラー: {e}")

                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if is_detail_page:
                    # 詳細ページの通知（席種情報を含む）
                    seat_info_text = f"\n席種: {seat_type}" if seat_type else ""
                    date_info_text = f"\n日付: {matched_date}" if matched_date else ""
                    message = f"[{target_name}] 詳細ページでチケット販売を検知しました！{date_info_text}{seat_info_text}\n時刻: {now}\n検知文言: {detect_text}\n{url}"
                else:
                    # 親ページの通知（席種情報なし）
                    date_info_text = f"\n日付: {matched_date}" if matched_date else ""
                    message = f"[{target_name}] チケット販売を検知しました！{date_info_text}\n時刻: {now}\n検知文言: {detect_text}\n{url}"

                # 通知（非同期で送信 - メインスレッドをブロックしない）
                use_broadcast = False
                if notification_config:
                    # コマンドラインオプションで指定された場合
                    use_broadcast = notification_config.get("broadcast", False)
                else:
                    # config.jsonの設定に従う
                    use_broadcast = cfg.get("use_broadcast", False)
                
                # 非同期で通知送信（LINEとメールを並列実行、メインスレッドはブロックされない）
                send_notifications_async(cfg, message, target_name, use_broadcast=use_broadcast)

                notified.add(notify_key)
                found_any = True
                
                # リンクがある場合は保存
                if detail_link:
                    detected_links.append({
                        'url': detail_link,
                        'source_target': target_name,
                        'detected_date': matched_date
                    })
                
                print(f"[{target_name}] 通知完了。キー '{notify_key}' を記録しました。")
                break  # 1つ見つかったらこの日付のチェック終了

            except Exception as e:
                print(f"[{target_name}] [{idx+1}/{len(items)}] 要素処理エラー: {e}")
                continue

    except Exception as e:
        print(f"[{target_name}] チェック中エラー:", e)

    return found_any, detected_links

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
        target_configs = []  # 動的に追加される可能性があるため、リストで管理
        for target in watch_targets:
            try:
                page = browser.new_page()
                print(f"[{target['name']}] タブを開いています: {target['url']}")
                # 初期ロードはdomcontentloadedで十分（networkidleはタイムアウトしやすい）
                page.goto(target['url'], wait_until="domcontentloaded", timeout=30000)
                pages.append(page)
                target_configs.append(target)
            except Exception as e:
                print(f"[{target['name']}] 初期ロードエラー: {e}")
                print(f"[{target['name']}] タイムアウトしましたが、監視を続行します")
                # エラーが発生してもページは作成されているので、追加を試みる
                try:
                    pages.append(page)
                    target_configs.append(target)
                except:
                    print(f"[{target['name']}] ページの追加に失敗しました。スキップします")

        print("\n全タブの初期ロード完了。監視を開始します。\n")

        while True:
            try:
                found_any = False
                new_detail_targets = []  # 新しく追加する詳細ページ監視対象

                # 各ターゲットを並行チェック（それぞれ専用のタブで）
                for idx, target in enumerate(target_configs):
                    page = pages[idx]
                    result, detected_links = check_target(page, target, cfg, notified, notification_config)
                    found_any = found_any or result
                    
                    # 詳細ページ監視が有効で、リンクが検知された場合
                    if detected_links and target.get("enable_detail_watch", False):
                        watch_all = target.get("watch_all_detected_links", False)
                        links_to_watch = detected_links if watch_all else [detected_links[0]]  # 全てまたは最初の1つ
                        
                        for link_info in links_to_watch:
                            detail_url = link_info['url']
                            source_name = link_info['source_target']
                            detected_date = link_info['detected_date']
                            
                            # 既に監視中のURLかチェック
                            if any(t['url'] == detail_url for t in target_configs):
                                print(f"[{source_name}] 詳細ページは既に監視中です: {detail_url}")
                                continue
                            
                            # 詳細ページ用の設定を作成
                            # detail_target_dates/detail_detect_textが未指定の場合は元の設定を使用
                            detail_target_dates = target.get("detail_target_dates")
                            if detail_target_dates is None or len(detail_target_dates) == 0:
                                detail_target_dates = target.get("target_dates", [])
                            
                            detail_detect_text = target.get("detail_detect_text")
                            if detail_detect_text is None or detail_detect_text == "":
                                detail_detect_text = target.get("detect_text", "")
                            
                            detail_config = {
                                "name": f"{source_name} - 詳細({detected_date})",
                                "url": detail_url,
                                "selector": target.get("detail_selector", ""),
                                "target_dates": detail_target_dates,
                                "detect_text": detail_detect_text,
                                "enable_detail_watch": False,  # 詳細ページの詳細ページは監視しない
                                "button_selector": target.get("button_selector", ""),
                                "detail_seat_types": target.get("detail_seat_types", [])  # 席種指定
                            }
                            
                            # 新しいタブを作成して監視対象に追加
                            try:
                                detail_page = browser.new_page()
                                print(f"[{detail_config['name']}] 詳細ページのタブを開いています: {detail_url}")
                                # domcontentloadedで十分（networkidleはタイムアウトしやすい）
                                detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                                pages.append(detail_page)
                                target_configs.append(detail_config)
                                new_detail_targets.append(detail_config['name'])
                                print(f"[{source_name}] 詳細ページ監視を開始しました: {detail_url}")
                            except Exception as e:
                                print(f"[{source_name}] 詳細ページの読み込みエラー: {e}")
                                # エラーが発生してもページは作成されている可能性があるので、追加を試みる
                                try:
                                    pages.append(detail_page)
                                    target_configs.append(detail_config)
                                    print(f"[{source_name}] エラーが発生しましたが、監視を続行します")
                                except:
                                    print(f"[{source_name}] 詳細ページの追加に失敗しました。スキップします")
                
                if new_detail_targets:
                    print(f"新しく追加された監視対象: {', '.join(new_detail_targets)}")

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
