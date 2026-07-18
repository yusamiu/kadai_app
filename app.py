from flask import Flask, render_template, request, redirect, url_for, session
from datetime import datetime
import os
import psycopg2
from psycopg2.extras import DictCursor

app = Flask(__name__)
app.secret_key = 'yusaku_secret_key_12345'

# --------------------------------------------------
# 🔑 Renderの金庫（データベース）に接続する関数
# --------------------------------------------------
def get_db_connection():
    # Renderの環境変数（後で設定します）から金庫のURLを読み込む
    database_url = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(database_url, sslmode='require')
    return conn

# --------------------------------------------------
# 🏗️ アプリ起動時に、金庫の中に「引き出し（テーブル）」を作る
# --------------------------------------------------
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # 課題を入れる引き出し
    cur.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            text TEXT NOT NULL,
            deadline TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL
        );
    ''')
    # 意見を入れる引き出し
    cur.execute('''
        CREATE TABLE IF NOT EXISTS opinions (
            id SERIAL PRIMARY KEY,
            created_at TEXT NOT NULL,
            text TEXT NOT NULL
        );
    ''')
    conn.commit()
    cur.close()
    conn.close()

# アプリ起動時に引き出しを自動作成
init_db()

# --------------------------------------------------
# 🏠 画面のルート（部屋）の設定
# --------------------------------------------------
@app.route('/')
def home():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    current_user = session['username']
    
    # 金庫から「自分の課題だけ」を期限が近い順に並び替えて持ってくる
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute(
        "SELECT username, text, deadline, subject, status FROM tasks WHERE username = %s ORDER BY deadline ASC",
        (current_user,)
    )
    db_tasks = cur.fetchall()
    cur.close()
    conn.close()
    
    user_tasks = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    for t in db_tasks:
        try:
            deadline_date = datetime.strptime(t['deadline'], '%Y-%m-%d')
            days_left = (deadline_date - today).days
        except:
            days_left = 0
            
        user_tasks.append({
            'username': t['username'],
            'text': t['text'],
            'deadline': t['deadline'],
            'subject': t['subject'],
            'status': t['status'],
            'days_left': days_left
        })
    
    return render_template('index.html', username=current_user, tasks=user_tasks)

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form.get('username')
        if username:
            session['username'] = username.strip()
            return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login_page'))

@app.route('/add', methods=['POST'])
def add_task():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    task_text = request.form.get('task')
    deadline = request.form.get('deadline')
    subject = request.form.get('subject')
    
    if task_text and deadline and subject:
        # 金庫に新しい課題をガチャンと入れる
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tasks (username, text, deadline, subject, status) VALUES (%s, %s, %s, %s, %s)",
            (session['username'], task_text, deadline, subject, 'yet')
        )
        conn.commit()
        cur.close()
        conn.close()
        
    return redirect(url_for('home'))

@app.route('/complete', methods=['POST'])
def complete_task():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    task_value = request.form.get('task_value')
    task_deadline = request.form.get('task_deadline')
    
    # 金庫のステータスを「done」に書き換える
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tasks SET status = 'done' WHERE username = %s AND text = %s AND deadline = %s",
        (session['username'], task_value, task_deadline)
    )
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('home'))

@app.route('/delete', methods=['POST'])
def delete_task():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    task_value = request.form.get('task_value')
    task_deadline = request.form.get('task_deadline')
    
    # 金庫からデータを完全に消去する
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM tasks WHERE username = %s AND text = %s AND deadline = %s",
        (session['username'], task_value, task_deadline)
    )
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('home'))

@app.route('/suggest', methods=['POST'])
def suggest():
    opinion_text = request.form.get('opinion')
    
    if opinion_text:
        # 金庫の意見箱引き出しに保存する
        conn = get_db_connection()
        cur = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        cur.execute(
            "INSERT INTO opinions (created_at, text) VALUES (%s, %s)",
            (now_str, opinion_text.strip())
        )
        conn.commit()
        cur.close()
        conn.close()
            
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)