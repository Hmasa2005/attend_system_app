from flask import Flask, render_template, request, redirect, url_for, jsonify
import psycopg2
from datetime import datetime
import subprocess
import threading
import time
import socket
import json

app = Flask(__name__)

DB_CONFIG = {
    'dbname': 'attendDB',
    'user': '',
    'password': '',
    'host': '',
    'port': 
}

# ==========================================
# Bluetooth チェック関数群
# ==========================================
def ping_device(address):
    if not address:
        return 0
    try:
        subprocess.run(["sudo", "l2ping", "-c", "1", address],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return 1  # 在席
    except subprocess.CalledProcessError:
        return 0  # 不在

def update_seat_status(address, status):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    if status == 1:
        cur.execute("UPDATE seats SET status=%s, last_present_time=%s WHERE bt_address=%s",
                    (status, datetime.now(), address))
    else:
        cur.execute("UPDATE seats SET status=%s WHERE bt_address=%s", (status, address))
    conn.commit()
    cur.close()
    conn.close()

def refresh_all_statuses():
    """ 全Bluetooth端末の在席状態を更新 """
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT bt_address FROM seats WHERE bt_address IS NOT NULL AND bt_address <> ''")
    addresses = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    for address in addresses:
        status = ping_device(address)
        update_seat_status(address, status)

def periodic_refresh():
    """ 定期的にBluetoothを監視 """
    while True:
        refresh_all_statuses()
        time.sleep(5)

# ==========================================
# 杉浦用の研究室ステータス更新
# ==========================================
def update_sugiura_status(new_status):
    """ 杉浦 昌 の status を更新（1=在席, 2=研究室在室） """
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    now = datetime.now()
    cur.execute("UPDATE seats SET status=%s, last_present_time=%s WHERE name=%s",
                (new_status, now, "杉浦 昌"))
    conn.commit()
    cur.close()
    conn.close()

# ==========================================
# TCPサーバ（ESP32用）: CDS値を受信して更新
# ==========================================
def tcp_sensor_server():
    HOST = '0.0.0.0'
    PORT = 5001
    CDS_THRESHOLD = 500  # 明るさの閾値

    print(f"[INFO] Sensor TCP Server running on port {PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()

        while True:
            conn, addr = s.accept()
            with conn:
                print(f"[INFO] Connection from {addr}")
                data = conn.recv(1024).decode().strip()
                if not data:
                    continue

                try:
                    obj = json.loads(data)
                    cds = obj.get("cds", 0)
                except json.JSONDecodeError:
                    print("[WARN] JSON decode error:", data)
                    continue
                
                conn_pg = psycopg2.connect(**DB_CONFIG)
                cur_pg = conn_pg.cursor()
                cur_pg.execute("SELECT bt_address FROM seats WHERE name=%s", ("杉浦 昌",))
                row = cur_pg.fetchone()
                cur_pg.close()
                conn_pg.close()

                bt_address = row[0] if row and row[0] else None

                # Bluetooth優先チェック
                bt_conn = ping_device(bt_address)  # ←杉浦のBluetoothアドレスに置換
                if bt_conn == 1:
                    update_sugiura_status(1)  # 在席
                    print("[UPDATE] 杉浦 昌: 在席（Bluetooth反応あり）")
                elif cds > CDS_THRESHOLD:
                    update_sugiura_status(2)  # 研究室在室
                    print(f"[UPDATE] 杉浦 昌: 研究室在室（CDS={cds}）")
                else:
                    # CDS低下かつBluetooth不在なら不在
                    conn_pg = psycopg2.connect(**DB_CONFIG)
                    cur_pg = conn_pg.cursor()
                    cur_pg.execute("UPDATE seats SET status=0 WHERE name=%s", ("杉浦 昌",))
                    conn_pg.commit()
                    cur_pg.close()
                    conn_pg.close()
                    print(f"[UPDATE] 杉浦 昌: 不在（CDS={cds}, BTなし）")

                conn.sendall(b"OK\n")

# ==========================================
# Flask API・HTML
# ==========================================
@app.route("/api/attendance")
def api_attendance():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT name, status, last_present_time FROM seats ORDER BY status DESC, name")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    data = []
    for row in rows:
        if row[1] == 1:
            status_str = '在席'
        elif row[1] == 2:
            status_str = '研究室在室'
        else:
            status_str = '不在'
        data.append({
            'name': row[0],
            'status': status_str,
            'last_present_time': row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else '----'
        })

    return jsonify({
        "seats": data,
        "search_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route("/")
def index():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT name, status, last_present_time FROM seats ORDER BY status DESC, name")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    data = []
    for row in rows:
        if row[1] == 1:
            status_str = '在席'
        elif row[1] == 2:
            status_str = '研究室在室'
        else:
            status_str = '不在'
        data.append({
            'name': row[0],
            'status': status_str,
            'last_present_time': row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else '----'
        })
    return render_template("attendance2.html",
                           seats=data,
                           search_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route("/edit", methods=["GET"])
def edit_address_form():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT name FROM seats ORDER BY name")
    names = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return render_template("edit.html", names=names)

@app.route("/update_address", methods=["POST"])
def update_address():
    name = request.form.get("name")
    new_address = request.form.get("new_address")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("UPDATE seats SET bt_address=%s WHERE name=%s", (new_address, name))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("index"))

# ==========================================
# メイン起動部
# ==========================================
if __name__ == "__main__":
    # Bluetooth周期監視スレッド
    t_refresh = threading.Thread(target=periodic_refresh, daemon=True)
    t_refresh.start()

    # ESP32用CDSサーバスレッド
    t_sensor = threading.Thread(target=tcp_sensor_server, daemon=True)
    t_sensor.start()

    # Flask起動
    app.run(host='0.0.0.0', port=5000, debug=True)
