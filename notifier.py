# notifier.py
import socket
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate
import requests
import threading

# タイムアウト（秒）
# ※ 短くしすぎると失敗率が上がります
LINE_HTTP_TIMEOUT_SEC = 0.3
SMTP_TIMEOUT_SEC = 1.0

def send_line_push(token, user_id, message, notification_disabled=False):
    """
    単一ユーザーにLINEプッシュメッセージを送信
    
    Args:
        token: LINE Channel Access Token
        user_id: ユーザーID（文字列）
        message: メッセージテキスト
        notification_disabled: 通知を無効にするかどうか（サイレント通知）
    """
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}],
        "notificationDisabled": notification_disabled
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=LINE_HTTP_TIMEOUT_SEC)
        if r.status_code == 200:
            mode = "（サイレント）" if notification_disabled else ""
            print(f"LINE通知送信成功{mode} (ユーザーID: {user_id})")
        else:
            print(f"LINE通知失敗 (ユーザーID: {user_id}):", r.status_code, r.text)
    except Exception as e:
        print(f"LINE送信例外 (ユーザーID: {user_id}):", e)

def send_line_push_to_all(token, user_ids, message, notification_disabled=False):
    """
    複数のユーザーにLINEプッシュメッセージを送信
    
    Args:
        token: LINE Channel Access Token
        user_ids: ユーザーIDのリスト
        message: メッセージテキスト
        notification_disabled: 通知を無効にするかどうか（サイレント通知）
    """
    if not user_ids:
        print("送信先ユーザーIDが指定されていません")
        return
    
    success_count = 0
    fail_count = 0
    
    for user_id in user_ids:
        try:
            send_line_push(token, user_id, message, notification_disabled=notification_disabled)
            success_count += 1
        except Exception as e:
            print(f"ユーザー {user_id} への送信失敗: {e}")
            fail_count += 1
    
    mode = "（サイレント）" if notification_disabled else ""
    print(f"LINE通知送信完了{mode}: 成功 {success_count}件, 失敗 {fail_count}件 (合計 {len(user_ids)}件)")

def send_line_broadcast(token, message, notification_disabled=False):
    """
    友達追加した全員にLINEブロードキャストメッセージを送信
    （ユーザーIDの管理が不要で、友達追加した全員に自動送信）
    
    Args:
        token: LINE Channel Access Token
        message: メッセージテキスト
        notification_disabled: 通知を無効にするかどうか（サイレント通知）
    """
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {
        "messages": [{"type": "text", "text": message}],
        "notificationDisabled": notification_disabled
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=LINE_HTTP_TIMEOUT_SEC)
        if r.status_code == 200:
            mode = "（サイレント）" if notification_disabled else ""
            print(f"LINEブロードキャスト送信成功{mode}（友達追加した全員に送信）")
        else:
            print(f"LINEブロードキャスト送信失敗: {r.status_code}, {r.text}")
    except Exception as e:
        print(f"LINEブロードキャスト送信例外: {e}")

def send_mail_ipv4(cfg, subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["smtp_user"]
    msg["To"] = cfg["mail_to"]
    msg["Date"] = formatdate()

    try:
        addrinfo = socket.getaddrinfo(cfg["smtp_host"], cfg["smtp_port"], socket.AF_INET, socket.SOCK_STREAM)
        ipv4_addr = addrinfo[0][4][0]
        with smtplib.SMTP_SSL(
            ipv4_addr,
            cfg["smtp_port"],
            local_hostname="localhost",
            timeout=SMTP_TIMEOUT_SEC,
        ) as s:
            s.set_debuglevel(0)
            s.login(cfg["smtp_user"], cfg["smtp_password"])
            s.send_message(msg)
        print("メール送信成功")
    except Exception as e:
        print("メール送信失敗:", e)

def send_notifications_async(cfg, message, target_name, use_broadcast=False):
    """
    通知を非同期で送信（LINEとメールを並列実行）
    
    Args:
        cfg: 設定辞書
        message: メッセージテキスト
        target_name: ターゲット名
        use_broadcast: ブロードキャスト送信を使用するかどうか
    """
    def send_line():
        """LINE通知を送信（バックグラウンドスレッド）"""
        try:
            token = cfg["line_channel_access_token"]
            notification_disabled = cfg.get("notification_disabled", False)
            
            if use_broadcast:
                send_line_broadcast(token, message, notification_disabled)
            else:
                # 複数ユーザーIDに対応
                user_ids = []
                if "line_user_ids" in cfg and isinstance(cfg["line_user_ids"], list):
                    user_ids = cfg["line_user_ids"]
                if "line_user_id" in cfg and cfg["line_user_id"]:
                    if cfg["line_user_id"] not in user_ids:
                        user_ids.append(cfg["line_user_id"])
                
                if user_ids:
                    send_line_push_to_all(token, user_ids, message, notification_disabled)
        except Exception as e:
            print(f"LINE通知送信エラー: {e}")
    
    def send_mail():
        """メール通知を送信（バックグラウンドスレッド）"""
        try:
            send_mail_ipv4(cfg, f"チケット販売検知 [{target_name}]", message)
        except Exception as e:
            print(f"メール送信エラー: {e}")
    
    # LINE通知とメール送信を並列で実行
    line_thread = threading.Thread(target=send_line, daemon=True)
    mail_thread = threading.Thread(target=send_mail, daemon=True)
    
    line_thread.start()
    mail_thread.start()
    
    # スレッドの開始をログに記録（完了は待たない）
    print(f"[{target_name}] 通知送信を開始しました（非同期）")
