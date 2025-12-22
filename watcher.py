# watcher.py
import json
import time
import argparse
import unicodedata
import threading
import os
import queue
import asyncio
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from notifier import send_notifications_async

# 非同期ロックはrun_watcher_async内で作成（グローバル変数として保持）

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

# スクリーンショット取得用のキュー（非同期処理のため）
screenshot_queue = queue.Queue()

def capture_screenshot_async(page, target_name, url, state_change, timestamp):
    """スクリーンショット取得をキューに追加（非同期処理）"""
    try:
        # スクリーンショット保存ディレクトリを作成
        screenshots_dir = Path("logs/screenshots")
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # ファイル名を生成（タイムスタンプ + ターゲット名 + 状態）
        safe_name = "".join(c for c in target_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')
        filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{safe_name}_{state_change}.png"
        filepath = screenshots_dir / filename
        
        # キューに追加（メインスレッドで後で処理される）
        screenshot_queue.put({
            'page': page,
            'filepath': filepath,
            'target_name': target_name
        })
        print(f"[{target_name}] スクリーンショット取得をキューに追加しました: {filepath}")
    except Exception as e:
        print(f"[{target_name}] スクリーンショットキュー追加エラー: {e}")

async def process_screenshot_queue():
    """キューに溜まったスクリーンショットを処理（非同期で実行）"""
    processed = 0
    max_process = 1  # 一度に処理する最大数（検知速度を最優先、1件のみ処理）
    
    while not screenshot_queue.empty() and processed < max_process:
        try:
            item = screenshot_queue.get_nowait()
            page = item['page']
            filepath = item['filepath']
            target_name = item['target_name']
            
            # スクリーンショットを取得（非同期で実行）
            await page.screenshot(path=str(filepath), full_page=True)
            print(f"[{target_name}] スクリーンショットを保存しました: {filepath}")
            processed += 1
        except queue.Empty:
            break
        except Exception as e:
            print(f"[{target_name}] スクリーンショット取得エラー: {e}")
    
    return processed

def log_detection_change_async(target_name, url, state_change, timestamp, detect_text, matched_date=None, seat_type=None):
    """検知状態の変化をログに記録（非同期で実行）"""
    def _log():
        try:
            # ログディレクトリを作成
            logs_dir = Path("logs")
            logs_dir.mkdir(parents=True, exist_ok=True)
            
            log_file = logs_dir / "detection_changes.log"
            
            # ログメッセージを構築
            state_text = "検知文言が現れました" if state_change == "appeared" else "検知文言が消えました"
            log_message = f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] [{target_name}] {state_text}\n"
            log_message += f"  URL: {url}\n"
            log_message += f"  検知文言: {detect_text}\n"
            if matched_date:
                log_message += f"  対象日付: {matched_date}\n"
            if seat_type:
                log_message += f"  席種: {seat_type}\n"
            log_message += "\n"
            
            # ログファイルに追記
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_message)
            
            print(f"[{target_name}] 検知状態の変化をログに記録しました: {state_text}")
        except Exception as e:
            print(f"[{target_name}] ログ記録エラー: {e}")
    
    # バックグラウンドスレッドで実行
    thread = threading.Thread(target=_log, daemon=True)
    thread.start()

async def check_target_async(page, target_config, cfg, notified, notified_by_target, notification_config=None, notified_lock=None):
    """単一ターゲットの監視処理
    戻り値:
      - detected_any: 検知条件（target_dates AND detect_text）を満たすブロックが存在したか
      - detected_links: 検知した要素のリンクのリスト
      - notified_new: 新規通知を送ったか（通知済みスキップの場合はFalse）
    """
    target_name = target_config["name"]
    url = target_config["url"]
    target_key = (target_name, url)
    selector = target_config.get("selector", "")
    target_dates = target_config["target_dates"]
    detect_text = target_config.get("detect_text", "")
    # button_selector = target_config.get("button_selector", "")
    enable_detail_watch = target_config.get("enable_detail_watch", False)
    detail_seat_types = target_config.get("detail_seat_types", [])  # 席種指定（詳細ページ用）
    # 詳細ページかどうか（ターゲット単位で固定）
    is_detail_page_target = "詳細" in target_name

    detected_any = False
    notified_new = False
    detected_links = []  # 検知した要素のリンクを保存

    try:
        # ページをリロード（gotoより高速、キャッシュも活用可能）
        # domcontentloadedを使用（リダイレクト検知のため、commitより安全）
        # タイムアウトを1秒に短縮して高速化
        try:
            await page.reload(wait_until="domcontentloaded", timeout=1000)
        except Exception:
            # reloadが失敗した場合（初回など）はgotoを使用
            await page.goto(url, wait_until="domcontentloaded", timeout=1000)
        
        # リダイレクトを検知（アクセス過多ページなどに飛ばされた場合）
        current_url = page.url
        if current_url != url and ("error" in current_url.lower() or "access" in current_url.lower() or "too" in current_url.lower()):
            print(f"[{target_name}] 警告: リダイレクトが検知されました。現在のURL: {current_url}")
            # リダイレクトされた場合は少し待ってから再試行
            await asyncio.sleep(1)
            await page.goto(url, wait_until="domcontentloaded", timeout=1000)

        # セレクタが指定されている場合は待機、なければキーワードで検索
        items = []
        used_fallback_text_search = False  # フォールバック（get_by_text）経由かどうか
        if selector:
            try:
                # セレクタの待機時間を短縮して高速化
                await page.wait_for_selector(selector, timeout=2000)
                items = await page.locator(selector).all()
                print(f"[{target_name}] {len(items)}個の要素を検出")
            except PWTimeout:
                print(f"[{target_name}] {selector}が見つかりません。キーワードで要素を検索します。")
                used_fallback_text_search = True
                # セレクタが見つからない場合、target_datesを含む要素を全て取得
                items = []
                for td in target_dates:
                    # Playwrightのget_by_textで部分一致検索（正規表現使用）
                    try:
                        # 全要素からテキストで検索
                        matching_elements = await page.get_by_text(td, exact=False).all()
                        print(f"[{target_name}] '{td}'を含む要素: {len(matching_elements)}個")
                        items.extend(matching_elements)
                    except Exception as e:
                        print(f"[{target_name}] テキスト検索エラー: {e}")

                if not items:
                    print(f"[{target_name}] キーワードを含む要素が見つかりませんでした")
                    return detected_any, detected_links, notified_new
        else:
            # selectorが未指定の場合もキーワードで検索
            items = []
            used_fallback_text_search = True
            for td in target_dates:
                try:
                    matching_elements = await page.get_by_text(td, exact=False).all()
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
                    if await valiation_input.count() > 0:
                        seat_type = await valiation_input.get_attribute('value')
                    else:
                        # ticketSelect__textから席種名を抽出
                        text_elem = item.locator('.ticketSelect__text').first
                        if await text_elem.count() > 0:
                            text_content = await text_elem.inner_text()
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

                # innerText を evaluate で確実に取得（タイムアウト付き、短縮して高速化）
                text = await item.evaluate("el => el.innerText || ''", timeout=2000)
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

                if normalized_detect:
                    if used_fallback_text_search:
                        # フォールバック(get_by_text)は「広い要素」を掴んで別ブロックの文言まで含むことがある。
                        # そのため、target_dates(=matched_date)の近傍に detect_text がある場合のみ検知扱いにする。
                        normalized_matched_date = ' '.join(matched_date.split()) if matched_date else ""
                        idx = normalized_text.find(normalized_matched_date) if normalized_matched_date else -1
                        # 近傍ウィンドウ（前後）: 誤検知しやすいヘッダー/フッター混入を避けるため小さめに制限
                        window_before = 50
                        window_after = 250
                        if idx >= 0:
                            start = max(0, idx - window_before)
                            end = min(len(normalized_text), idx + len(normalized_matched_date) + window_after)
                            near_text = normalized_text[start:end]
                        else:
                            # 日付位置が取れない場合は安全側に倒してスキップ（フォールバック誤検知を防ぐ）
                            near_text = ""

                        if normalized_detect not in near_text:
                            print(f"[{target_name}] フォールバック近傍に'{detect_text}'が見つかりません（スキップ）")
                            print(f"[{target_name}] normalized_text: {normalized_text}")
                            continue
                    else:
                        if normalized_detect not in normalized_text:
                            print(f"[{target_name}] ブロック内に'{detect_text}'が見つかりません")
                            print(f"[{target_name}] normalized_text: {normalized_text}")
                            continue

                print(f"[{target_name}] ブロック内に'{detect_text}'を検出！")
                detected_any = True

                # 詳細ページかどうか（通知メッセージ・通知キー用）
                is_detail_page = is_detail_page_target
                
                # 通知キーの生成（親ページと詳細ページで完全に分離）
                # target_nameとURLを含めることで、親ページと詳細ページで確実に異なる通知キーになる
                # フォールバック(get_by_text)経由は誤検知しやすいので、通知済みキーを通常検知と分離する
                key_mode = "FB" if used_fallback_text_search else "BLK"
                if is_detail_page:
                    # 詳細ページ: target_name、URL、席種情報を含める
                    seat_info = f"席種:{seat_type}" if seat_type else ""
                    notify_key = f"{key_mode}||詳細||{target_name}||{url}||{matched_date}||{detect_text}||{seat_info}"
                else:
                    # 親ページ: target_name、URLを含める（席種情報は含めない）
                    notify_key = f"{key_mode}||親||{target_name}||{url}||{matched_date}||{detect_text}||"

                # 既に通知済みかチェック
                if notified_lock:
                    async with notified_lock:
                        was_notified = notify_key in notified
                else:
                    was_notified = notify_key in notified
                if was_notified:
                    print(f"[{target_name}] 既に通知済み（スキップ）: {notify_key}")
                    # 既に通知済みの場合は検知状態は維持されている（変化なし）
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

                if notified_lock:
                    async with notified_lock:
                        notified.add(notify_key)
                        # ターゲット単位で「通知済みキー」を紐付けて保持（消えたら解除して再出現で再通知できるようにする）
                        if target_key not in notified_by_target:
                            notified_by_target[target_key] = set()
                        notified_by_target[target_key].add(notify_key)
                else:
                    notified.add(notify_key)
                    if target_key not in notified_by_target:
                        notified_by_target[target_key] = set()
                    notified_by_target[target_key].add(notify_key)
                notified_new = True
                
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

    return detected_any, detected_links, notified_new

async def run_watcher_async(notification_config=None):
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
    # ターゲット単位で通知済みキーを保持（検知が消えたら解除して再出現で再通知）
    # key: (target_name, url), value: set(notify_key)
    notified_by_target = {}
    # 各ターゲットの前回の検知状態を記録（検知状態の変化を検知するため）
    # key: (target_name, url), value: True=検知中, False=未検知
    previous_detection_states = {}
    
    # 非同期ロックを作成（共有データへのアクセス制御用）
    notified_lock = asyncio.Lock()

    print("=== 監視設定 ===")
    for idx, target in enumerate(watch_targets, 1):
        print(f"{idx}. {target['name']}")
        print(f"   URL: {target['url']}")
        print(f"   対象: {target['target_dates']}")
        print(f"   検知ワード: {target.get('detect_text', '')}")
    print("検知後の動作:", "終了" if stop_after_detection else "継続監視")
    print("ブラウザモード:", "Headless（バックグラウンド）" if headless else "表示")
    print("================\n")

    async with async_playwright() as p:
        browser_args = ["--start-maximized"] if not headless else []
        
        # 各ターゲットごとに別のブラウザコンテキスト（ウィンドウ）を作成（並列処理で高速化）
        browsers = []  # 各ターゲット用のブラウザ（launchしたブラウザインスタンス）
        contexts = []  # 各ターゲット用のコンテキスト（ページを作成するためのコンテキスト）
        pages = []  # 各ターゲット用のページ
        target_configs = []  # 動的に追加される可能性があるため、リストで管理
        
        # 最初のターゲット: persistent_contextを使用してCookieを取得（ログイン状態を保持）
        first_browser_context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            executable_path=chrome_path,
            headless=headless,
            args=browser_args
        )
        first_page = await first_browser_context.new_page()
        await first_page.goto(watch_targets[0]['url'], wait_until="domcontentloaded", timeout=30000)
        
        # 最初のブラウザからCookieを取得（ログイン状態を共有するため）
        shared_cookies = []
        try:
            shared_cookies = await first_browser_context.cookies()
        except Exception as e:
            print(f"Cookie取得エラー（無視）: {e}")
        
        # 最初のターゲットも通常のブラウザに切り替え（別ウィンドウとして開くため）
        await first_browser_context.close()
        
        # すべてのターゲットで通常のブラウザを起動（別ウィンドウとして開く）
        for idx, target in enumerate(watch_targets):
            try:
                # 通常のブラウザを起動（別ウィンドウ）
                browser = await p.chromium.launch(
                    executable_path=chrome_path,
                    headless=headless,
                    args=browser_args
                )
                browsers.append(browser)
                
                # 新しいコンテキストを作成
                context = await browser.new_context()
                contexts.append(context)
                
                # 最初のブラウザからCookieをコピー（ログイン状態を共有）
                if shared_cookies:
                    try:
                        await context.add_cookies(shared_cookies)
                    except Exception as e:
                        print(f"[{target['name']}] Cookieコピーエラー（無視）: {e}")
                
                # 各コンテキストで1つのページを開く
                page = await context.new_page()
                
                print(f"[{target['name']}] ウィンドウを開いています: {target['url']}")
                # 初期ロードはdomcontentloadedで十分（networkidleはタイムアウトしやすい）
                await page.goto(target['url'], wait_until="domcontentloaded", timeout=30000)
                pages.append(page)
                target_configs.append(target)
            except Exception as e:
                print(f"[{target['name']}] 初期ロードエラー: {e}")
                print(f"[{target['name']}] タイムアウトしましたが、監視を続行します")
                # エラーが発生してもブラウザとページは作成されている可能性があるので、追加を試みる
                try:
                    browsers.append(browser)
                    contexts.append(context)
                    pages.append(page)
                    target_configs.append(target)
                except:
                    print(f"[{target['name']}] ブラウザ/ページの追加に失敗しました。スキップします")

        print("\n全ウィンドウの初期ロード完了。監視を開始します。\n")

        while True:
            try:
                any_new_notification = False
                any_detected = False
                new_detail_targets = []  # 新しく追加する詳細ページ監視対象
                
                # すべてのターゲットを並列でチェック（asyncio.gatherで並列実行）
                async def check_target_wrapper(idx, target, page, context):
                    """各ターゲットのチェックを非同期で実行"""
                    try:
                        # check_target_asyncを実行（ロックは内部で必要な部分だけ使用）
                        detected_any, detected_links, notified_new = await check_target_async(
                            page, target, cfg, notified, notified_by_target, notification_config, notified_lock
                        )
                        
                        # 検知状態の変化をチェック
                        target_key = (target["name"], target["url"])
                        current_state = detected_any  # True=検知中, False=未検知
                        
                        async with notified_lock:
                            previous_state = previous_detection_states.get(target_key, False)
                        
                        # 検知状態が変化した場合
                        state_change = None
                        if current_state != previous_state:
                            if current_state and not previous_state:
                                # 検知文言が現れた
                                state_change = "appeared"
                            elif not current_state and previous_state:
                                # 検知文言が消えた
                                state_change = "disappeared"
                                # 「検知→検知なし→検知」で再通知できるように、当該ターゲットの通知済みキーを解除
                                async with notified_lock:
                                    keys = notified_by_target.get(target_key, set())
                                    if keys:
                                        for k in list(keys):
                                            if k in notified:
                                                notified.remove(k)
                                        notified_by_target[target_key] = set()
                        
                        if state_change:
                            timestamp = datetime.now()
                            detect_text = target.get("detect_text", "")
                            
                            # スクリーンショット取得をキューに追加（非同期処理）
                            capture_screenshot_async(page, target["name"], target["url"], state_change, timestamp)
                            # ログを非同期で記録
                            log_detection_change_async(
                                target["name"], 
                                target["url"], 
                                state_change, 
                                timestamp,
                                detect_text,
                                matched_date=None,  # 詳細情報は必要に応じて追加
                                seat_type=None
                            )
                        
                        # 現在の状態を記録
                        async with notified_lock:
                            previous_detection_states[target_key] = current_state
                        
                        # 詳細ページ監視が有効で、リンクが検知された場合
                        detail_configs_to_add = []
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
                                
                                # 新しいタブを作成して監視対象に追加（親ページと同じブラウザコンテキストを使用）
                                try:
                                    # 親ページと同じコンテキストを使用
                                    detail_page = await context.new_page()
                                    print(f"[{detail_config['name']}] 詳細ページのタブを開いています: {detail_url}")
                                    # domcontentloadedで十分（networkidleはタイムアウトしやすい）
                                    await detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                                    
                                    detail_configs_to_add.append({
                                        'page': detail_page,
                                        'config': detail_config,
                                        'context': context
                                    })
                                    
                                    print(f"[{source_name}] 詳細ページ監視を開始しました: {detail_url}")
                                except Exception as e:
                                    print(f"[{source_name}] 詳細ページの読み込みエラー: {e}")
                                    # エラーが発生してもページは作成されている可能性があるので、追加を試みる
                                    try:
                                        detail_configs_to_add.append({
                                            'page': detail_page,
                                            'config': detail_config,
                                            'context': context
                                        })
                                        print(f"[{source_name}] エラーが発生しましたが、監視を続行します")
                                    except:
                                        print(f"[{source_name}] 詳細ページの追加に失敗しました。スキップします")
                        
                        return {
                            'detected_any': detected_any,
                            'notified_new': notified_new,
                            'detail_configs': detail_configs_to_add
                        }
                    except Exception as e:
                        print(f"[{target['name']}] チェックエラー: {e}")
                        return {
                            'detected_any': False,
                            'notified_new': False,
                            'detail_configs': []
                        }
                
                # すべてのターゲットを並列でチェック（asyncio.gatherで並列実行）
                tasks = []
                for idx, target in enumerate(target_configs):
                    page = pages[idx]
                    context = contexts[idx]
                    tasks.append(check_target_wrapper(idx, target, page, context))
                
                # すべてのタスクを並列で実行
                results = await asyncio.gather(*tasks)
                
                # 結果を統合
                for result in results:
                    any_detected = any_detected or result['detected_any']
                    any_new_notification = any_new_notification or result['notified_new']
                    
                    # 詳細ページを追加
                    for detail_info in result['detail_configs']:
                        pages.append(detail_info['page'])
                        target_configs.append(detail_info['config'])
                        contexts.append(detail_info['context'])
                        new_detail_targets.append(detail_info['config']['name'])
                
                if new_detail_targets:
                    print(f"新しく追加された監視対象: {', '.join(new_detail_targets)}")

                # スクリーンショットキューを処理（非同期で追加されたスクリーンショットを取得）
                # 検知速度を優先するため、スクリーンショット処理は最小限に（最大1件まで、高速化）
                processed_count = await process_screenshot_queue()
                if processed_count > 0:
                    print(f"スクリーンショットを{processed_count}件処理しました。")

                if any_new_notification:
                    print("新規検知→通知しました。")
                    if stop_after_detection:
                        print("stop_after_detection=true のため終了します。")
                        break
                    else:
                        print("継続監視します。次ループまで待機します。")
                        await asyncio.sleep(interval)
                        continue

                if any_detected:
                    # 検知はあったが通知済みでスキップされたケース
                    print(f"{datetime.now():%H:%M:%S} - 検知あり（通知済みのため通知なし）。{interval}s後再試行。")
                else:
                    print(f"{datetime.now():%H:%M:%S} - 新規検知なし。{interval}s後再試行。")
                await asyncio.sleep(interval)

            except Exception as e:
                print("監視ループ例外:", e)
                await asyncio.sleep(interval)

        # すべてのブラウザを閉じる
        for browser in browsers:
            try:
                await browser.close()
            except Exception as e:
                print(f"ブラウザクローズエラー: {e}")

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
    
    asyncio.run(run_watcher_async(notification_config))
