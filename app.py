from flask import Flask, render_template, request, redirect, url_for, session
from datetime import datetime, timedelta
import os
import psycopg2
from psycopg2.extras import DictCursor

app = Flask(__name__)
app.secret_key = 'yusaku_secret_key_12345'

# --------------------------------------------------
# 🔑 Renderの金庫（データベース）に接続する関数
# --------------------------------------------------
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(database_url, sslmode='require')
    return conn

# --------------------------------------------------
# 🏗️ アプリ起動時に、金庫の中に「引き出し（テーブル）」を作る
# --------------------------------------------------
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
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

init_db()

# 💡 リクエストが来るたびに「ログイン状態を30日維持する」を設定する安全な記述法
@app.before_request
def make_session_permanent():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(days=30)

# --------------------------------------------------
# 🏠 メイン画面（ホーム部屋）
# --------------------------------------------------
@app.route('/')
def home():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    current_user = session['username']
    
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

# --------------------------------------------------
# 🔑 ログイン画面
# --------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    # すでにログインしているなら、ログイン画面は見せずにホームへ飛ばす（自動ログイン）
    if 'username' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username')
        if username:
            session['username'] = username.strip()
            return redirect(url_for('home'))
    return render_template('login.html')

# --------------------------------------------------
# 🚪 ログアウト処理
# --------------------------------------------------
@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login_page'))

# --------------------------------------------------
# ➕ 課題の追加
# --------------------------------------------------
@app.route('/add', methods=['POST'])
def add_task():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    task_text = request.form.get('task')
    deadline = request.form.get('deadline')
    subject = request.form.get('subject')
    
    if task_text and deadline and subject:
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

# --------------------------------------------------
# ✅ 課題の完了
# --------------------------------------------------
@app.route('/complete', methods=['POST'])
def complete_task():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    task_value = request.form.get('task_value')
    task_deadline = request.form.get('task_deadline')
    
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

# --------------------------------------------------
# ❌ 課題の削除
# --------------------------------------------------
@app.route('/delete', methods=['POST'])
def delete_task():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    task_value = request.form.get('task_value')
    task_deadline = request.form.get('task_deadline')
    
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

# --------------------------------------------------
# 📩 意見箱の送信
# --------------------------------------------------
@app.route('/suggest', methods=['POST'])
def suggest():
    opinion_text = request.form.get('opinion')
    
    if opinion_text:
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

# --------------------------------------------------
# 🔐 管理者用の隠しページ（ユーザー一覧＆意見箱の確認）
# --------------------------------------------------
@app.route('/admin-yusaku-xyz777')
def admin_page():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT DISTINCT username FROM tasks ORDER BY username;")
    users = [row[0] for row in cur.fetchall()]
    
    opinions = []
    try:
        cur.execute("SELECT text, created_at FROM opinions ORDER BY id DESC;")
        opinions = cur.fetchall()
    except Exception:
        conn.rollback()
    
    cur.close()
    conn.close()
    
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>管理者専用ページ</title>
        <style>
            body { font-family: Arial, sans-serif; background: #f4f7f6; padding: 20px; color: #333; max-width: 600px; margin: 0 auto; }
            h1 { color: #2c3e50; border-bottom: 2px solid #2c3e50; padding-bottom: 10px; font-size: 20px; }
            h2 { font-size: 16px; color: #16a085; margin-top: 30px; }
            ul { list-style: none; padding: 0; }
            li { background: white; padding: 10px 15px; margin-bottom: 8px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 14px; }
            .time { font-size: 11px; color: #7f8c8d; display: block; margin-top: 4px; }
            .back-btn { display: inline-block; background: #7f8c8d; color: white; text-decoration: none; padding: 8px 12px; border-radius: 4px; font-size: 13px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <a href="/" class="back-btn">← アプリに戻る</a>
        <h1>📊 優作総帥の秘密の管理部屋</h1>
        
        <h2>👤 これまでにログインしたユーザー名 ({% len_users %})</h2>
        <ul>
            REPLACE_USER_LIST
        </ul>
        
        <h2>📩 意見箱に届いたメッセージ ({% len_opinions %})</h2>
        <ul>
            REPLACE_OPINION_LIST
        </ul>
    </body>
    </html>
    """
    
    rendered = html_content.replace("{% len_users %}", str(len(users))).replace("{% len_opinions %}", str(len(opinions)))
    
    user_list_html = ""
    for u in users:
        user_list_html += f"<li><strong>{u}</strong> さん</li>"
    if not users:
        user_list_html = '<li style="color: #999;">まだ誰も登録していません</li>'
    rendered = rendered.replace("REPLACE_USER_LIST", user_list_html)
    
    opinion_list_html = ""
    for op in opinions:
        opinion_list_html += f"<li><div>{op[0]}</div><span class='time'>受信日時: {op[1]}</span></li>"
    if not opinions:
        opinion_list_html = '<li style="color: #999;">まだ意見は届いていません</li>'
    rendered = rendered.replace("REPLACE_OPINION_LIST", opinion_list_html)
    
    return rendered

if __name__ == '__main__':
    app.run(debug=True)