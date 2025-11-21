# controller.py
import json
import os
import subprocess
import signal
from flask import Flask, request, jsonify, abort
from notifier import send_line_push

app = Flask(__name__)
PIDFILE = "watcher.pid"

def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

cfg = load_config()

# ---- helper
def read_pid():
    if os.path.exists(PIDFILE):
        with open(PIDFILE, "r") as f:
            return int(f.read().strip())
    return None

def write_pid(pid):
    with open(PIDFILE, "w") as f:
        f.write(str(pid))

def remove_pid():
    if os.path.exists(PIDFILE):
        os.remove(PIDFILE)

def is_running():
    pid = read_pid()
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        remove_pid()
        return False

# ---- start/stop watcher
@app.route("/start", methods=["POST"])
def start_watcher():
    secret = request.args.get("secret")
    if secret != cfg.get("management_secret"):
        return abort(403)
    if is_running():
        return jsonify({"status":"already_running"})
    # start watcher.py
    proc = subprocess.Popen(["python", "watcher.py"], creationflags=0)
    write_pid(proc.pid)
    send_line_push(cfg["line_channel_access_token"], cfg["line_user_id"], "監視を開始しました。")
    return jsonify({"status":"started", "pid": proc.pid})

@app.route("/stop", methods=["POST"])
def stop_watcher():
    secret = request.args.get("secret")
    if secret != cfg.get("management_secret"):
        return abort(403)
    pid = read_pid()
    if not pid:
        return jsonify({"status":"not_running"})
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    remove_pid()
    send_line_push(cfg["line_channel_access_token"], cfg["line_user_id"], "監視を停止しました。")
    return jsonify({"status":"stopped"})

@app.route("/status", methods=["GET"])
def status():
    secret = request.args.get("secret")
    if secret != cfg.get("management_secret"):
        return abort(403)
    return jsonify({"running": is_running()})

@app.route("/set", methods=["POST"])
def set_config():
    secret = request.args.get("secret")
    if secret != cfg.get("management_secret"):
        return abort(403)
    body = request.json or {}
    config = load_config()
    # allow changing target_dates (list) or check_interval_sec, target_url etc.
    for k in ["target_dates", "check_interval_sec", "target_url", "button_text"]:
        if k in body:
            config[k] = body[k]
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    return jsonify({"status":"ok", "config": config})

# ---- LINE webhook endpoint
@app.route("/callback", methods=["POST"])
def callback():
    # LINE webhook events (簡易): テキストメッセージをコマンドとして処理
    ev = request.get_json()
    try:
        for e in ev.get("events", []):
            typ = e.get("type")
            if typ != "message": 
                continue
            user = e["source"].get("userId")
            if user != cfg.get("line_user_id"):
                # 認可外のユーザーは無視
                continue
            txt = e["message"].get("text", "").strip().lower()
            if txt == "start":
                # call local /start with secret
                subprocess.Popen(["curl", "-X", "POST", f"http://localhost:5000/start?secret={cfg.get('management_secret')}"])
            elif txt == "stop":
                subprocess.Popen(["curl", "-X", "POST", f"http://localhost:5000/stop?secret={cfg.get('management_secret')}"])
            elif txt == "status":
                running = is_running()
                send_line_push(cfg["line_channel_access_token"], cfg["line_user_id"], f"稼働中: {running}")
            elif txt.startswith("set "):
                # set target_dates=11月16日,11月15日 など
                try:
                    payload = txt.replace("set ", "", 1)
                    if "=" in payload:
                        k, v = payload.split("=",1)
                        k = k.strip()
                        v = v.strip()
                        if k == "target_dates":
                            dates = [d.strip() for d in v.split(",")]
                            subprocess.Popen(["curl", "-X", "POST", "-H", "Content-Type: application/json",
                                              "-d", json.dumps({"target_dates": dates}), f"http://localhost:5000/set?secret={cfg.get('management_secret')}"])
                            send_line_push(cfg["line_channel_access_token"], cfg["line_user_id"], f"設定更新: {k} = {dates}")
                        else:
                            subprocess.Popen(["curl", "-X", "POST", "-H", "Content-Type: application/json",
                                              "-d", json.dumps({k: v}), f"http://localhost:5000/set?secret={cfg.get('management_secret')}"])
                            send_line_push(cfg["line_channel_access_token"], cfg["line_user_id"], f"設定更新: {k} = {v}")
                except Exception as ex:
                    send_line_push(cfg["line_channel_access_token"], cfg["line_user_id"], f"設定更新エラー: {ex}")
        return "OK"
    except Exception:
        return "ERR", 400

if __name__ == "__main__":
    # 本番では systemd / Windowsサービス 等で常駐させる
    app.run(port=5000, host="127.0.0.1")
