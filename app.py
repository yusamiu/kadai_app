import os
import json
import logging
from datetime import datetime, timedelta
import pytz  # 🔔 日本時間の計算用
from flask import Flask, render_template, request, redirect, session, jsonify, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from pywebpush import webpush, WebPushException

# ロギングの設定（エラーの追跡用）
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

app = Flask(__name__)
# セッション暗号化キー
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-yusaku-xyz-9999-alpha')

# --- 🛰️ Supabase (PostgreSQL) 設定 ---
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///local_fallback.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- 🔔 WebPush通知用の鍵設定 ---
# 環境変数にあればそれを優先し、なければハードコードした公開鍵を使用
DEFAULT_VAPID_PUBLIC_KEY = "BLFvsP57Nmst6JA6TS3joiz6Cnf6G1dC5mOCrEHBBsulBNcVPtKJy9zNw1SmKHA67wxLb9V3TjtAB2jJh08J8j0"
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY') or DEFAULT_VAPID_PUBLIC_KEY
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'mailto:admin@yusaku-xyz.com')

app.config['VAPID_PUBLIC_KEY'] = VAPID_PUBLIC_KEY
app.config['VAPID_PRIVATE_KEY'] = VAPID_PRIVATE_KEY

db = SQLAlchemy(app)

# --- 🗄️ データベースのテーブル定義 ---
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    deadline = db.Column(db.String(50), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='yet')
    created_at = db.Column(db.String(50), nullable=False)
    completed_at = db.Column(db.String(50), nullable=True)

class Suggestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    opinion = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.String(50), nullable=False)

class LoginHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    login_time = db.Column(db.String(50), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.Text, nullable=False)
    auth = db.Column(db.Text, nullable=False)
    registered_at = db.Column(db.String(50), nullable=False)


# --- 🔔 1日前リマインダー通知処理 ---
def check_and_send_daily_reminders():
    try:
        jst = pytz.timezone('Asia/Tokyo')
        now_jst = datetime.now(jst)
        
        logging.info("【テスト通知】Cronエンドポイントからリマインダー処理を強制実行します！")
        
        private_key = VAPID_PRIVATE_KEY or app.config.get('VAPID_PRIVATE_KEY')
        if not private_key:
            logging.error("【自動通知】VAPID_PRIVATE_KEY が設定されていません。")
            return

        # 明日の日付
        tomorrow = now_jst.date() + timedelta(days=1)
        tomorrow_str = tomorrow.strftime('%Y-%m-%d')
        
        logging.info(f"【デバッグ】明日({tomorrow_str})が期限の未完了タスクを探します...")

        # ① 未完了タスクを検索
        upcoming_tasks = Task.query.filter(
            Task.deadline.like(f"{tomorrow_str}%"),
            Task.status == 'yet'
        ).all()

        logging.info(f"【デバッグ】見つかった対象タスク数: {len(upcoming_tasks)}件")

        # もし見つからない場合、今DBにあるすべての未完了タスクを出力してみる
        if not upcoming_tasks:
            all_yet = Task.query.filter_by(status='yet').all()
            logging.info(f"【デバッグ】(確認用) DB内の未完了タスク全{len(all_yet)}件のデータ:")
            for t in all_yet:
                logging.info(f" -> タスク名: {t.text} | 期限: '{t.deadline}' | 作成者: '{t.username}'")
            logging.info("【自動通知】1日前リマインダー送信完了。成功: 0件")
            return

        success_count = 0

        # ② タスクが見つかった場合
        for task in upcoming_tasks:
            logging.info(f"【デバッグ】タスク「{task.text}」(作成者: '{task.username}') の通知宛先を探します...")
            
            subscriptions = Subscription.query.filter_by(username=task.username).all()
            logging.info(f"【デバッグ】ユーザー '{task.username}' の通知登録(Subscription)数: {len(subscriptions)}件")
            
            for sub in subscriptions:
                subscription_info = {
                    "endpoint": sub.endpoint,
                    "keys": {
                        "p256dh": sub.p256dh,
                        "auth": sub.auth
                    }
                }
                
                payload = json.dumps({
                    "title": "タスクの期限が明日です！🚨",
                    "body": f"「{task.text}」の期限が迫っています。明日中に完了させましょう！",
                    "icon": "/static/icon.png",
                    "badge": "/static/icon.png"
                })
                
                try:
                    webpush(
                        subscription_info=subscription_info,
                        data=payload,
                        vapid_private_key=private_key,
                        vapid_claims={"sub": ADMIN_EMAIL}
                    )
                    success_count += 1
                except WebPushException as ex:
                    logging.warning(f"【自動通知】WebPush送信失敗 ({task.username}): {str(ex)}")
                except Exception as e:
                    logging.error(f"【自動通知】送信時エラー: {str(e)}")

        logging.info(f"【自動通知】1日前リマインダー送信完了。成功: {success_count}件")
        
    except Exception as general_e:
        logging.error(f"【自動通知】全体エラー発生: {str(general_e)}")


# 認証フィルター
def is_logged_in():
    return 'username' in session


# --- 1. ルート：サービスworkerの配信用（両方のURLパスに対応） ---
@app.route('/service-worker.js')
@app.route('/static/service-worker.js')
def service_worker():
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
        
        if not username:
            flash('ユーザー名を入力してください。', 'error')
            return render_template('login.html')
            
        session['username'] = username
        session.permanent = True
        
        # 【Supabase保存】ログイン履歴
        try:
            new_log = LoginHistory(
                username=username,
                login_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                ip_address=request.remote_addr or 'Unknown'
            )
            db.session.add(new_log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logging.error(f"ログイン履歴の保存中にエラー: {str(e)}")
            
        logging.info(f"ユーザーログイン成功: {username}")
        return redirect(url_for('index'))
        
    return render_template('login.html')


# --- 3. ルート：ログアウト処理 ---
@app.route('/logout')
def logout():
    username = session.get('username', '未知のユーザー')
    session.clear()
    logging.info(f"ユーザーログアウト: {username}")
    return redirect(url_for('login'))


# --- 4. ルート：メインダッシュボード（タスク一覧） ---
@app.route('/')
def index():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    username = session['username']
    
    # 【Supabase取得】ログインユーザーのタスクのみを取得
    tasks = Task.query.filter_by(username=username).all()
    
    # 🇯🇵 日本時間（JST）の「今日」を取得して正確に計算する
    jst = pytz.timezone('Asia/Tokyo')
    today_jst = datetime.now(jst).date()
    
    user_tasks = []
    for t in tasks:
        task_dict = {
            'username': t.username,
            'text': t.text,
            'deadline': t.deadline,
            'subject': t.subject,
            'status': t.status,
            'created_at': t.created_at
        }
        try:
            if t.deadline:
                deadline_date = datetime.strptime(t.deadline, '%Y-%m-%d').date()
                task_dict['days_left'] = (deadline_date - today_jst).days
            else:
                task_dict['days_left'] = 999
        except Exception as e:
            logging.error(f"日付計算エラー (タスク: {t.text}): {str(e)}")
            task_dict['days_left'] = 999
        user_tasks.append(task_dict)
            
    return render_template('index.html', username=username, tasks=user_tasks, vapid_public_key=VAPID_PUBLIC_KEY)


# --- 5. ルート：新規タスク追加 ---
@app.route('/add', methods=['POST'])
def add_task():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    text = request.form.get('task', '').strip()
    deadline = request.form.get('deadline', '').strip()
    
    subject_select = request.form.get('subject', '').strip()
    subject_custom = request.form.get('subject_custom', '').strip()
    
    if subject_select == 'その他' and subject_custom:
        subject = subject_custom
    else:
        subject = subject_select
    
    if not text or not deadline or not subject:
        flash('すべての項目を正しく入力してください。', 'error')
        return redirect(url_for('index'))
        
    try:
        new_task = Task(
            username=session['username'],
            text=text,
            deadline=deadline,
            subject=subject,
            status='yet',
            created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        db.session.add(new_task)
        db.session.commit()
        logging.info(f"タスク追加: {session['username']} -> {text} ({subject})")
    except Exception as e:
        db.session.rollback()
        logging.error(f"タスク追加エラー: {str(e)}")
        flash('データの保存に失敗しました。', 'error')
    
    return redirect(url_for('index'))


# --- 6. ルート：タスク完了処理 ---
@app.route('/complete', methods=['POST'])
def complete_task():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    task_value = request.form.get('task_value', '').strip()
    task_deadline = request.form.get('task_deadline', '').strip()
    username = session['username']
    
    task = Task.query.filter_by(username=username, text=task_value, deadline=task_deadline, status='yet').first()
    
    if task:
        try:
            task.status = 'done'
            task.completed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            db.session.commit()
            logging.info(f"タスク完了: {username} -> {task_value}")
        except Exception as e:
            db.session.rollback()
            logging.error(f"タスク完了エラー: {str(e)}")
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
    
    task = Task.query.filter_by(username=username, text=task_value, deadline=task_deadline).first()
    
    if task:
        try:
            db.session.delete(task)
            db.session.commit()
            logging.info(f"タスク削除: {username} -> {task_value}")
        except Exception as e:
            db.session.rollback()
            logging.error(f"タスク削除エラー: {str(e)}")
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
        
    try:
        new_suggestion = Suggestion(
            username=session['username'],
            opinion=opinion,
            created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        db.session.add(new_suggestion)
        db.session.commit()
        logging.info(f"意見箱に投稿を受領: {session['username']} -> {opinion[:20]}...")
    except Exception as e:
        db.session.rollback()
        logging.error(f"意見投稿エラー: {str(e)}")
        
    return redirect(url_for('index'))


# --- 9. ルート：WebPush通知用の購読鍵の登録・更新 ---
@app.route('/subscribe', methods=['POST'])
def subscribe():
    try:
        sub_data = request.get_json()
        if not sub_data or 'endpoint' not in sub_data:
            return jsonify({"status": "error", "message": "無効な購読データ形式です。"}), 400
            
        current_user = session.get('username', 'guest')
        endpoint = sub_data['endpoint']
        keys = sub_data.get('keys', {})
        p256dh = keys.get('p256dh', '')
        auth = keys.get('auth', '')

        # 既存登録の確認
        existing = Subscription.query.filter_by(endpoint=endpoint).first()
        if not existing:
            # 新規登録
            new_sub = Subscription(
                username=current_user,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                registered_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
            db.session.add(new_sub)
            logging.info(f"新規通知端末を登録しました: ユーザー={current_user}")
        else:
            # 既存端末の情報更新（ユーザー変更や鍵の再生成に対応）
            existing.username = current_user
            existing.p256dh = p256dh
            existing.auth = auth
            existing.registered_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logging.info(f"既存通知端末を更新しました: ユーザー={current_user}")

        db.session.commit()
        return jsonify({"status": "success", "message": "通知登録が正常に完了しました。"})

    except Exception as e:
        db.session.rollback()
        logging.error(f"通知登録処理中に致命的なエラー: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# --- 10. ルート：UptimeRobot等のCron呼び出し用エンドポイント ---
@app.route('/api/cron/reminders')
def trigger_reminders():
    check_and_send_daily_reminders()
    return "Reminders checked!", 200


# --- 11. ルート：👑 管理者コントロールパネル ---
@app.route('/admin-yusaku-xyz777', methods=['GET', 'POST'])
def admin_page():
    if request.method == 'POST':
        action = request.form.get('action', '').strip()
        
        # 意見箱の全消去
        if action == 'clear_suggestions':
            try:
                Suggestion.query.delete()
                db.session.commit()
                logging.info("管理者により意見箱データが完全に初期化されました。")
            except Exception as e:
                db.session.rollback()
                logging.error(f"意見箱削除エラー: {str(e)}")
            return redirect(url_for('admin_page'))
            
        # ログイン履歴の全消去
        elif action == 'clear_history':
            try:
                LoginHistory.query.delete()
                db.session.commit()
                logging.info("管理者によりログイン履歴データが完全に初期化されました。")
            except Exception as e:
                db.session.rollback()
                logging.error(f"ログイン履歴削除エラー: {str(e)}")
            return redirect(url_for('admin_page'))
            
        # 全体通知の一斉配信
        elif action == 'broadcast':
            title = request.form.get('title', '管理者からのお知らせ').strip()
            body = request.form.get('body', 'これは全体配信テスト通知です。').strip()
            
            subs = Subscription.query.all()
            if not subs:
                logging.warning("通知対象の登録端末が1件もありません。")
                return redirect(url_for('admin_page'))
                
            payload = json.dumps({
                "title": title,
                "body": body,
                "icon": "/static/icon.png",
                "badge": "/static/icon.png"
            })
            
            success_count = 0
            fail_count = 0
            
            for sub in subs:
                try:
                    clean_sub = {
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh,
                            "auth": sub.auth
                        }
                    }
                    webpush(
                        subscription_info=clean_sub,
                        data=payload,
                        vapid_private_key=VAPID_PRIVATE_KEY,
                        vapid_claims={"sub": ADMIN_EMAIL}
                    )
                    success_count += 1
                except WebPushException as ex:
                    logging.warning(f"無効なプッシュ通知キーを検出・削除します: {str(ex)}")
                    try:
                        db.session.delete(sub)
                        db.session.commit()
                    except:
                        db.session.rollback()
                    fail_count += 1
                except Exception as e:
                    logging.error(f"通知送信中に予期せぬ例外: {str(e)}")
                    
            logging.info(f"全体通知完了。成功: {success_count}件, 自動削除された無効端末: {fail_count}件")
            return redirect(url_for('admin_page'))

    # 管理者画面用のデータ取得
    suggestions_raw = Suggestion.query.order_by(Suggestion.id.desc()).all()
    suggestions = [{
        'username': s.username,
        'opinion': s.opinion,
        'created_at': s.created_at
    } for s in suggestions_raw]

    history_raw = LoginHistory.query.order_by(LoginHistory.id.desc()).limit(100).all()
    login_history = [{
        'username': h.username,
        'login_time': h.login_time,
        'ip_address': h.ip_address
    } for h in history_raw]

    subscriptions_count = Subscription.query.count()

    return render_template(
        'admin.html',
        suggestions=suggestions,
        login_history=login_history,
        subs_count=subscriptions_count
    )


# --- 12. アプリケーション起動エントリーポイント ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=port)