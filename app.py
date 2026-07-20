import os
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, jsonify, url_for, flash
from pywebpush import webpush, WebPushException

# ロギングの設定（エラーの追跡用）
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

app = Flask(__name__)
# セッション暗号化キー（Renderの環境変数から取得、なければ安全なデフォルト値）
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-yusaku-xyz-9999-alpha')

# --- WebPush設定（Renderの環境変数から取得） ---
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'mailto:admin@yusaku-xyz.com')

# --- データ保存ファイルの定義 ---
DATA_FILE = 'tasks.json'
SUBS_FILE = 'subscriptions.json'
SUGGESTIONS_FILE = 'suggestions.json'
HISTORY_FILE = 'login_history.json'
USER_FILE = 'users.json'  # ユーザーアカウント管理用（もしあれば）

# --- データ入出力用ヘルパー関数群（バリデーション付き） ---
def load_json_data(file_path):
    """指定されたJSONファイルからデータを安全に読み込む関数"""
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except json.JSONDecodeError:
        logging.error(f"JSONのパースに失敗しました: {file_path}. 空のリストを返します。")
        return []
    except Exception as e:
        logging.error(f"ファイル読み込みエラー ({file_path}): {str(e)}")
        return []

def save_json_data(file_path, data):
    """指定されたデータをJSONファイルへ安全に保存する関数"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logging.error(f"ファイル保存エラー ({file_path}): {str(e)}")
        return False

# --- 認証フィルター（デコレータ相当のチェック） ---
def is_logged_in():
    return 'username' in session

# --- 1. ルート：サービworkerの配信用（PWA対応） ---
@app.route('/service-worker.js')
def service_worker():
    """フロントエンドからService Workerを要求された際、正しいMIMEタイプで返却する"""
    try:
        return app.send_static_file('service-worker.js')
    except Exception as e:
        logging.error(f"Service Worker配信エラー: {str(e)}")
        return "Service Worker Not Found", 404

# --- 2. ルート：ログイン画面 ＆ 認証処理 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in():
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        # バリデーション：空文字チェック
        if not username or not password:
            flash('ユーザー名とパスワードを入力してください。', 'error')
            return render_template('login.html')
            
        # 簡易ユーザー認証（必要に応じてハッシュ化やDB照合に変更可能）
        # ここでは誰でも自由な名前で即座にアカウントを作成してログインできる仕様
        session['username'] = username
        session.permanent = True  # セッションの永続化
        
        # 【機能追加】ログイン履歴を保存するロジック
        try:
            history = load_json_data(HISTORY_FILE)
            new_log = {
                'username': username,
                'login_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'ip_address': request.remote_addr or 'Unknown'
            }
            history.insert(0, new_log)  # 先頭（最新）に追加
            history = history[:100]     # 最大100件まで保持
            save_json_data(HISTORY_FILE, history)
        except Exception as e:
            logging.error(f"ログイン履歴の保存中にエラー: {str(e)}")
            
        logging.info(f"ユーザーログイン成功: {username}")
        return redirect(url_for('index'))
        
    return render_template('login.html')

# --- 3. ルート：ログアウト処理 ---
@app.route('/logout')
def logout():
    username = session.get('username', '未知のユーザー')
    session.clear()  # セッション情報を完全に消去
    logging.info(f"ユーザーログアウト: {username}")
    return redirect(url_for('login'))

# --- 4. ルート：メインダッシュボード（タスク一覧） ---
@app.route('/')
def index():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    username = session['username']
    all_tasks = load_json_data(DATA_FILE)
    
    # 現在ログインしているユーザーのタスクのみをフィルタリング
    user_tasks = [task for task in all_tasks if task.get('username') == username]
    
    # 各タスクの残り日数をリアルタイム計算
    today = datetime.now().date()
    for task in user_tasks:
        try:
            deadline_str = task.get('deadline')
            if deadline_str:
                deadline_date = datetime.strptime(deadline_str, '%Y-%m-%d').date()
                task['days_left'] = (deadline_date - today).days
            else:
                task['days_left'] = 999
        except Exception as e:
            logging.error(f"日付計算エラー (タスク: {task.get('text')}): {str(e)}")
            task['days_left'] = 999
            
    return render_template('index.html', username=username, tasks=user_tasks, vapid_public_key=VAPID_PUBLIC_KEY)

# --- 5. ルート：新規タスク追加 ---
@app.route('/add', methods=['POST'])
def add_task():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    text = request.form.get('task', '').strip()
    deadline = request.form.get('deadline', '').strip()
    subject = request.form.get('subject', '').strip()
    
    # バリデーション：必要な情報が揃っているか
    if not text or not deadline or not subject:
        flash('すべての項目を正しく入力してください。', 'error')
        return redirect(url_for('index'))
        
    all_tasks = load_json_data(DATA_FILE)
    
    # 新しいタスクオブジェクトを作成して保存
    new_task = {
        'username': session['username'],
        'text': text,
        'deadline': deadline,
        'subject': subject,
        'status': 'yet',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    all_tasks.append(new_task)
    save_json_data(DATA_FILE, all_tasks)
    
    logging.info(f"タスク追加: {session['username']} -> {text}")
    return redirect(url_for('index'))

# --- 6. ルート：タスク完了処理 ---
@app.route('/complete', methods=['POST'])
def complete_task():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    task_value = request.form.get('task_value', '').strip()
    task_deadline = request.form.get('task_deadline', '').strip()
    username = session['username']
    
    all_tasks = load_json_data(DATA_FILE)
    updated = False
    
    # 特定のタスクを探してステータスを 'done' に変更
    for task in all_tasks:
        if (task.get('username') == username and 
            task.get('text') == task_value and 
            task.get('deadline') == task_deadline and 
            task.get('status') == 'yet'):
            task['status'] = 'done'
            task['completed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            updated = True
            break
            
    if updated:
        save_json_data(DATA_FILE, all_tasks)
        logging.info(f"タスク完了: {username} -> {task_value}")
    else:
        logging.warning(f"完了対象のタスクが見つかりません: {username} -> {task_value}")
        
    return redirect(url_for('index'))

# --- 7. ルート：タスク削除処理 ---
@app.route('/delete', methods=['POST'])
def delete_task():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    task_value = request.form.get('task_value', '').strip()
    task_deadline = request.form.get('task_deadline', '').strip()
    username = session['username']
    
    all_tasks = load_json_data(DATA_FILE)
    # 対象タスクを除外した新しいリストを作成
    filtered_tasks = [t for t in all_tasks if not (
        t.get('username') == username and 
        t.get('text') == task_value and 
        t.get('deadline') == task_deadline
    )]
    
    if len(all_tasks) != len(filtered_tasks):
        save_json_data(DATA_FILE, filtered_tasks)
        logging.info(f"タスク削除: {username} -> {task_value}")
    else:
        logging.warning(f"削除対象のタスクが見つかりません: {username} -> {task_value}")
        
    return redirect(url_for('index'))

# --- 8. ルート：意見箱への投稿受領 ---
@app.route('/suggest', methods=['POST'])
def suggest():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    opinion = request.form.get('opinion', '').strip()
    if not opinion:
        return redirect(url_for('index'))
        
    suggestions = load_json_data(SUGGESTIONS_FILE)
    new_suggestion = {
        'username': session['username'],
        'opinion': opinion,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    suggestions.insert(0, new_suggestion)  # 最新が上にくるように保持
    save_json_data(SUGGESTIONS_FILE, suggestions)
    
    logging.info(f"意見箱に投稿を受領: {session['username']} -> {opinion[:20]}...")
    return redirect(url_for('index'))

# --- 9. ルート：WebPush通知用の購読鍵の登録・更新 ---
@app.route('/subscribe', methods=['POST'])
def subscribe():
    """ブラウザ側で生成されたPushSubscriptionオブジェクトをサーバーに保存する"""
    try:
        sub_data = request.get_json()
        if not sub_data or 'endpoint' not in sub_data:
            return jsonify({"status": "error", "message": "無効な購読データ形式です。"}), 400
            
        subs = load_json_data(SUBS_FILE)
        
        # エンドポイントの重複チェック（すでに登録済みの場合は上書きせずスキップ）
        endpoints = [s.get('endpoint') for s in subs if isinstance(s, dict)]
        if sub_data['endpoint'] not in endpoints:
            # 誰の端末情報かを紐付けるためにユーザー名を付与しておく
            sub_data['username'] = session.get('username', 'guest')
            sub_data['registered_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            subs.append(sub_data)
            save_json_data(SUBS_FILE, subs)
            logging.info(f"新しい通知端末を登録しました。所属: {sub_data['username']}")
            
        return jsonify({"status": "success", "message": "通知登録が正常に完了しました。"})
    except Exception as e:
        logging.error(f"通知登録処理中に致命的なエラー: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 10. ルート：👑 管理者コントロールパネル ---
@app.route('/admin-yusaku-xyz777', methods=['GET', 'POST'])
def admin_page():
    # 常に最新のデータをJSONからロード
    suggestions = load_json_data(SUGGESTIONS_FILE)
    login_history = load_json_data(HISTORY_FILE)
    subscriptions_count = len(load_json_data(SUBS_FILE))

    if request.method == 'POST':
        action = request.form.get('action', '').strip()
        
        # アクション①: 意見箱データの全消去
        if action == 'clear_suggestions':
            if os.path.exists(SUGGESTIONS_FILE):
                try:
                    os.remove(SUGGESTIONS_FILE)
                    logging.info("管理者により意見箱データが完全に初期化されました。")
                except Exception as e:
                    logging.error(f"意見箱削除エラー: {str(e)}")
            return redirect(url_for('admin_page'))
            
        # アクション②: ログイン履歴データの全消去
        elif action == 'clear_history':
            if os.path.exists(HISTORY_FILE):
                try:
                    os.remove(HISTORY_FILE)
                    logging.info("管理者によりログイン履歴データが完全に初期化されました。")
                except Exception as e:
                    logging.error(f"ログイン履歴削除エラー: {str(e)}")
            return redirect(url_for('admin_page'))
            
        # アクション③: 登録されているすべての端末へ全体通知の一斉配信
        elif action == 'broadcast':
            title = request.form.get('title', '管理者からのお知らせ').strip()
            body = request.form.get('body', 'これは全体配信テスト通知です。').strip()
            
            subs = load_json_data(SUBS_FILE)
            if not subs:
                logging.warning("通知対象の登録端末が1件もありません。")
                return redirect(url_for('admin_page'))
                
            payload = json.dumps({
                "title": title,
                "body": body,
                "icon": "/static/icon.png",
                "badge": "/static/icon.png"
            })
            
            # 鍵が無効（期限切れなど）だった場合にリストから除外するための追跡
            valid_subs = []
            success_count = 0
            fail_count = 0
            
            for sub in subs:
                try:
                    # サブスクリプション情報から内部管理用の拡張キーを削除して通知モジュールに渡す
                    clean_sub = {k: v for k, v in sub.items() if k != 'username' and k != 'registered_at'}
                    
                    webpush(
                        subscription_info=clean_sub,
                        data=payload,
                        vapid_private_key=VAPID_PRIVATE_KEY,
                        vapid_claims={"sub": ADMIN_EMAIL}
                    )
                    valid_subs.append(sub)  # 送信成功したサブスクリプションを保持
                    success_count += 1
                except WebPushException as ex:
                    # 410 Gone や 404 Not Found など、無効になった古いプッシュキーを自動検知して排除
                    logging.warning(f"無効なプッシュ通知キーを検出・スキップします: {str(ex)}")
                    fail_count += 1
                except Exception as e:
                    logging.error(f"通知送信中に予期せぬ例外: {str(e)}")
                    valid_subs.append(sub)  # 一時的なネットワークエラーを考慮し一旦残す
                    
            # 有効なリストのみでJSONファイルを更新保存
            save_json_data(SUBS_FILE, valid_subs)
            logging.info(f"全体通知完了。成功: {success_count}件, 自動削除された無効端末: {fail_count}件")
            return redirect(url_for('admin_page'))

    return render_template(
        'admin.html', 
        suggestions=suggestions, 
        login_history=login_history,
        subs_count=subscriptions_count
    )

# --- 11. アプリケーション起動エントリーポイント ---
if __name__ == '__main__':
    # 開発環境と本番環境（Render）の双方に対応する環境適応型ポート設定
    port = int(os.environ.get('PORT', 5000))
    # Render上では debug=False を推奨しますが、調整しやすいよう標準動作で設定
    app.run(debug=True, host='0.0.0.0', port=port)