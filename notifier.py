# notifier.py
import socket
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate
import requests

def send_line_push(token, user_id, message):
    """
    単一ユーザーにLINEプッシュメッセージを送信
    
    Args:
        token: LINE Channel Access Token
        user_id: ユーザーID（文字列）
        message: メッセージテキスト
    """
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {"to": user_id, "messages": [{"type": "text", "text": message}]}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if r.status_code == 200:
            print(f"LINE通知送信成功 (ユーザーID: {user_id})")
        else:
            print(f"LINE通知失敗 (ユーザーID: {user_id}):", r.status_code, r.text)
    except Exception as e:
        print(f"LINE送信例外 (ユーザーID: {user_id}):", e)

def send_line_push_to_all(token, user_ids, message):
    """
    複数のユーザーにLINEプッシュメッセージを送信
    
    Args:
        token: LINE Channel Access Token
        user_ids: ユーザーIDのリスト
        message: メッセージテキスト
    """
    if not user_ids:
        print("送信先ユーザーIDが指定されていません")
        return
    
    success_count = 0
    fail_count = 0
    
    for user_id in user_ids:
        try:
            send_line_push(token, user_id, message)
            success_count += 1
        except Exception as e:
            print(f"ユーザー {user_id} への送信失敗: {e}")
            fail_count += 1
    
    print(f"LINE通知送信完了: 成功 {success_count}件, 失敗 {fail_count}件 (合計 {len(user_ids)}件)")

def send_line_broadcast(token, message):
    """
    友達追加した全員にLINEブロードキャストメッセージを送信
    （ユーザーIDの管理が不要で、友達追加した全員に自動送信）
    
    Args:
        token: LINE Channel Access Token
        message: メッセージテキスト
    """
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {"messages": [{"type": "text", "text": message}]}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if r.status_code == 200:
            print("LINEブロードキャスト送信成功（友達追加した全員に送信）")
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
        with smtplib.SMTP_SSL(ipv4_addr, cfg["smtp_port"], local_hostname='localhost') as s:
            s.set_debuglevel(0)
            s.login(cfg["smtp_user"], cfg["smtp_password"])
            s.send_message(msg)
        print("メール送信成功")
    except Exception as e:
        print("メール送信失敗:", e)
