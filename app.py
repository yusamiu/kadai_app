from flask import Flask, render_template, request, redirect, url_for, session
from datetime import datetime
import os

app = Flask(__name__)
# ログイン状態を管理するための秘密の鍵
app.secret_key = 'yusaku_secret_key_12345'

# データの保存先ファイル名
TASK_FILE = "tasks.txt"
OPINION_FILE = "opinions.txt"

# --------------------------------------------------
# 📝 便利な関数（ファイルからデータを読み書きする）
# --------------------------------------------------
def load_tasks():
    """ファイルからすべての課題を読み込む関数"""
    if not os.path.exists(TASK_FILE):
        return []
    
    tasks = []
    with open(TASK_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # データの分割 (ユーザー名, 課題名, 期限, 教科, 状態)
            parts = line.split(",")
            if len(parts) == 5:
                username = parts[0].strip()
                text = parts[1].strip()
                deadline_str = parts[2].strip()
                subject = parts[3].strip()
                status = parts[4].strip()
                
                # あと何日かを計算する
                try:
                    deadline_date = datetime.strptime(deadline_str, '%Y-%m-%d')
                    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    days_left = (deadline_date - today).days
                except:
                    days_left = 0
                
                tasks.append({
                    'username': username,
                    'text': text,
                    'deadline': deadline_str,
                    'subject': subject,
                    'status': status,
                    'days_left': days_left
                })
    return tasks

def save_tasks(tasks):
    """すべての課題をファイルに書き込んで保存する関数"""
    with open(TASK_FILE, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(f"{t['username']},{t['text']},{t['deadline']},{t['subject']},{t['status']}\n")

# --------------------------------------------------
# 🏠 画面のルート（部屋）の設定
# --------------------------------------------------
@app.route('/')
def home():
    """メイン画面を表示する部屋"""
    # もしログインしていなければ、ログイン画面へ強制転送
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    current_user = session['username']
    all_tasks = load_tasks()
    
    # ログインしている「自分のデータだけ」を抜き出す（フィルター）
    user_tasks = [t for t in all_tasks if t['username'] == current_user]
    
    # 提出日が古い順（期限が近い順）に並び替える
    user_tasks.sort(key=lambda x: x['deadline'])
    
    return render_template('index.html', username=current_user, tasks=user_tasks)

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    """ログイン画面の部屋"""
    if request.method == 'POST':
        username = request.form.get('username')
        if username:
            # セッションに名前を記録してログイン状態にする
            session['username'] = username.strip()
            return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    """ログアウト処理をする部屋"""
    session.pop('username', None)
    return redirect(url_for('login_page'))

@app.route('/add', methods=['POST'])
def add_task():
    """新しい課題を追加するアクション"""
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    task_text = request.form.get('task')
    deadline = request.form.get('deadline')
    subject = request.form.get('subject')
    
    if task_text and deadline and subject:
        all_tasks = load_tasks()
        # 新しい課題に「今のユーザー名」のラベルを貼って追加
        all_tasks.append({
            'username': session['username'],
            'text': task_text,
            'deadline': deadline,
            'subject': subject,
            'status': 'yet'
        })
        save_tasks(all_tasks)
        
    return redirect(url_for('home'))

@app.route('/complete', methods=['POST'])
def complete_task():
    """課題を完了状態にするアクション"""
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    task_value = request.form.get('task_value')
    task_deadline = request.form.get('task_deadline')
    
    all_tasks = load_tasks()
    for t in all_tasks:
        # 自分の課題、かつ名前と期限が一致するものを「done」にする
        if t['username'] == session['username'] and t['text'] == task_value and t['deadline'] == task_deadline:
            t['status'] = 'done'
            
    save_tasks(all_tasks)
    return redirect(url_for('home'))

@app.route('/delete', methods=['POST'])
def delete_task():
    """課題を完全に削除するアクション"""
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    task_value = request.form.get('task_value')
    task_deadline = request.form.get('task_deadline')
    
    all_tasks = load_tasks()
    # 削除対象以外のデータを残すことで削除を実現する
    filtered_tasks = []
    for t in all_tasks:
        if t['username'] == session['username'] and t['text'] == task_value and t['deadline'] == task_deadline:
            continue
        filtered_tasks.append(t)
        
    save_tasks(filtered_tasks)
    return redirect(url_for('home'))

@app.route('/suggest', methods=['POST'])
def suggest():
    """意見箱からメッセージを受け取るアクション"""
    opinion_text = request.form.get('opinion')
    
    if opinion_text:
        # 追記モード("a")で意見専用のノートに保存
        with open(OPINION_FILE, "a", encoding="utf-8") as f:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
            f.write(f"[{now_str}] {opinion_text.strip()}\n")
            
    return redirect(url_for('home'))

if __name__ == '__main__':
    # アプリケーションを起動 (デバッグモードオン)
    app.run(debug=True)