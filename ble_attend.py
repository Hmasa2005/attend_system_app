from flask import Flask, render_template, request, redirect, url_for, jsonify
import psycopg2
from datetime import datetime
import subprocess
import threading
import time

app = Flask(__name__)

DB_CONFIG = {
    'dbname': 'attendDB',
    'user': '',
    'password': '',
    'host': '',
    'port': 
}

last_search_time = None  # グローバル変数追加

def periodic_refresh():
    global last_search_time
    while True:
        refresh_all_statuses()
        last_search_time = datetime.now()  # ←ここで必ず更新
        time.sleep(5)

@app.route("/api/attendance")
def api_attendance():
    global last_search_time
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT name, status, last_present_time FROM seats ORDER BY status DESC, name")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    data = []
    for row in rows:
        data.append({
            'name': row[0],
            'status': '在席' if row[1] == 1 else '不在',
            'last_present_time': row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else '----'
        })
    search_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({"seats": data, "search_time": search_time_str})


def ping_device(address):
    if not address:
        # print(f"アドレス未設定: {address}")
        return 0
    try:
        result = subprocess.run(["sudo", "l2ping", "-c", "1", address], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"l2ping成功: {address}")
        return 1
    except subprocess.CalledProcessError as e:
        # print(f"l2ping失敗: {address} エラー: {e}")
        return 0

def update_seat_status(address, status):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    if status == 1:
        cur.execute("UPDATE seats SET status=%s, last_present_time=%s WHERE bt_address=%s", (status, datetime.now(), address))
    else:
        cur.execute("UPDATE seats SET status=%s WHERE bt_address=%s", (status, address))
    conn.commit()
    cur.close()
    conn.close()

def refresh_all_statuses():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT bt_address FROM seats WHERE bt_address IS NOT NULL AND bt_address <> ''")
    addresses = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    for address in addresses:
        status = ping_device(address)
        update_seat_status(address, status)

@app.route("/")
def index():
    global last_search_time
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT name, status, last_present_time FROM seats ORDER BY status DESC, name")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    data = []
    for row in rows:
        data.append({
            'name': row[0],
            'status': '在席' if row[1] == 1 else '不在',
            'last_present_time': row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else '----'
        })

    search_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return render_template("attendance.html", seats=data, search_time=search_time_str)

# BLEアドレス変更フォームの表示
@app.route("/edit", methods=["GET"])
def edit_address_form():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT name FROM seats ORDER BY name")
    names = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return render_template("edit.html", names=names)

# フォームから送られたBLEアドレスを更新
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

def periodic_refresh():
    while True:
        refresh_all_statuses()
        time.sleep(5)

if __name__ == "__main__":
    # バックグラウンドで定期実行スレッドを開始
    t = threading.Thread(target=periodic_refresh, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=True)
