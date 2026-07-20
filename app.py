import os
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import datetime
from urllib.parse import urlparse
from pywebpush import webpush, WebPushException
import json
import threading
import time

app = Flask(__name__)
app.secret_key = 'super-secret-key-yusaku'

# データベース接続関数
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL', 'postgres://localhost/kadai_app')
    conn = psycopg2.connect(database_url, sslmode='require')
    return conn

# データベースの初期化
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # ユーザーテーブル
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
    ''')
    # タスクテーブル
    cur.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            text TEXT NOT NULL,
            deadline DATE NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'yet'
        );
    ''')
    # 意見箱テーブル
    cur.execute('''
        CREATE TABLE IF NOT EXISTS suggestions (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            opinion TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # プッシュ通知の購読情報テーブル
    cur.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            subscription_json TEXT NOT NULL,
            UNIQUE(username, subscription_json)
        );
    ''')
    conn.commit()
    cur.close()
    conn.close()

# 💡 Render起動時（モジュール読み込み時）に安全に1度だけDBを初期化する方式に変更
try:
    init_db()
except Exception as e:
    print(f"【DB初期化エラー】起動時の接続に失敗しました: {e}")

# -----------------------------------------------------------------------------
# 🤖 自動通知システム（物理送信関数）
# -----------------------------------------------------------------------------
def send_webpush(subscription_json, title, body):
    """個別のスマホへ通知を物理的に送信する共通関数"""
    private_key = os.environ.get('VAPID_PRIVATE_KEY')
    if not private_key:
        print("【エラー】Renderの環境変数に VAPID_PRIVATE_KEY が設定されていません。")
        return False
        
    try:
        subscription_data = json.loads(subscription_json)
        webpush(
            subscription_info=subscription_data,
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=private_key,
            vapid_claims={"sub": "mailto:yusaku@example.com"}
        )
        return True
    except WebPushException as ex:
        print(f"【通知送信失敗】端末側で解除された可能性があります: {ex}")
        return False
    except Exception as e:
        print(f"【予期せぬエラー】: {e}")
        return False

# -----------------------------------------------------------------------------
# 🌐 画面遷移・WEBページの処理（ルーティング）
# -----------------------------------------------------------------------------

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    
    cur.execute('SELECT * FROM tasks WHERE username = %s ORDER BY deadline ASC', (username,))
    raw_tasks = cur.fetchall()
    
    tasks = []
    today = datetime.date.today()
    for row in raw_tasks:
        task_date = row['deadline']
        days_left = (task_date - today).days
        tasks.append({
            'text': row['text'],
            'deadline': task_date.isoformat(),
            'subject': row['subject'],
            'status': row['status'],
            'days_left': days_left
        })
        
    cur.close()
    conn.close()
    return render_template('index.html', username=username, tasks=tasks)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT * FROM users WHERE username = %s AND password = %s', (username, password))
        user = cur.fetchone()
        
        if user:
            session['username'] = username
            cur.close()
            conn.close()
            return redirect(url_for('index'))
        
        # ユーザーがいない場合は自動で新規登録させる
        cur.execute('SELECT * FROM users WHERE username = %s', (username,))
        exist_user = cur.fetchone()
        if not exist_user:
            cur.execute('INSERT INTO users (username, password) VALUES (%s, %s)', (username, password))
            conn.commit()
            session['username'] = username
            cur.close()
            conn.close()
            return redirect(url_for('index'))
            
        cur.close()
        conn.close()
        return "ログイン失敗: パスワードが違います。"
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/add', methods=['POST'])
def add_task():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    task_text = request.form['task']
    deadline = request.form['deadline']
    subject = request.form['subject']
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO tasks (username, text, deadline, subject, status) VALUES (%s, %s, %s, %s, %s)',
        (username, task_text, deadline, subject, 'yet')
    )
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

@app.route('/complete', methods=['POST'])
def complete_task():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    username = session['username']
    task_value = request.form['task_value']
    task_deadline = request.form['task_deadline']
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tasks SET status = 'done' WHERE username = %s AND text = %s AND deadline = %s",
        (username, task_value, task_deadline)
    )
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

@app.route('/delete', methods=['POST'])
def delete_task():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    username = session['username']
    task_value = request.form['task_value']
    task_deadline = request.form['task_deadline']
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM tasks WHERE username = %s AND text = %s AND deadline = %s",
        (username, task_value, task_deadline)
    )
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

@app.route('/suggest', methods=['POST'])
def suggest():
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    opinion = request.form['opinion']
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('INSERT INTO suggestions (username, opinion) VALUES (%s, %s)', (username, opinion))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

# -----------------------------------------------------------------------------
# 📲 通知デバイス登録用API受取口
# -----------------------------------------------------------------------------
@app.route('/subscribe', methods=['POST'])
def subscribe():
    if 'username' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    username = session['username']
    subscription_data = request.get_data(as_text=True)
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('''
            INSERT INTO subscriptions (username, subscription_json) 
            VALUES (%s, %s) 
            ON CONFLICT (username, subscription_json) DO NOTHING
        ''', (username, subscription_data))
        conn.commit()
        return jsonify({"success": True}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# -----------------------------------------------------------------------------
# 👑 管理者用隠し部屋
# -----------------------------------------------------------------------------
@app.route('/admin-yusaku-xyz777', methods=['GET', 'POST'])
def admin_page():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'broadcast':
            title = request.form.get('title', '管理者からのお知らせ')
            body = request.form.get('body', 'これはテスト通知です。')
            
            cur.execute('SELECT subscription_json FROM subscriptions')
            all_subs = cur.fetchall()
            
            success_count = 0
            for row in all_subs:
                if send_webpush(row['subscription_json'], title, body):
                    success_count += 1
            return f"配信完了: {success_count} 件の端末に手動で送信しました。"
            
        elif action == 'clear_suggestions':
            cur.execute('DELETE FROM suggestions')
            conn.commit()
            return redirect(url_for('admin_page'))
            
    cur.execute('SELECT * FROM suggestions ORDER BY created_at DESC')
    all_suggestions = cur.fetchall()
    
    cur.close()
    conn.close()
    return render_template('admin.html', suggestions=all_suggestions)

# -----------------------------------------------------------------------------
# 🌟 完全無料の自動通知キッカケ（UptimeRobot用の超安全版URL）
# -----------------------------------------------------------------------------
@app.route('/cron-yusaku-trigger-999')
def cron_trigger():
    conn = None
    cur = None
    try:
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        
        cur.execute('''
            SELECT username, text, subject 
            FROM tasks 
            WHERE deadline = %s AND status = 'yet'
        ''', (tomorrow,))
        tomorrow_tasks = cur.fetchall()
        
        send_count = 0
        for task in tomorrow_tasks:
            target_user = task['username']
            task_title = task['text']
            subject_name = task['subject']
            
            cur.execute('SELECT subscription_json FROM subscriptions WHERE username = %s', (target_user,))
            subs = cur.fetchall()
            
            notification_title = "タスク管理アプリ"
            notification_body = f"「{subject_name}」の「{task_title}」の期限が明日に迫っています！"
            
            for sub in subs:
                if send_webpush(sub['subscription_json'], notification_title, notification_body):
                    send_count += 1
                    
        return f"自動通知の処理が完了しました！送信件数: {send_count}件"

    except Exception as e:
        print(f"【トリガー内エラー】: {e}")
        return f"エラーが発生しました: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)