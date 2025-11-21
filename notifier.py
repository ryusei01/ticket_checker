# notifier.py
import socket
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate
import requests

def send_line_push(token, user_id, message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {"to": user_id, "messages": [{"type": "text", "text": message}]}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if r.status_code == 200:
            print("LINE通知送信成功")
        else:
            print("LINE通知失敗:", r.status_code, r.text)
    except Exception as e:
        print("LINE送信例外:", e)

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
