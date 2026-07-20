// 🔔 スマホが通知（プッシュイベント）を受け取った時に発動する処理
self.addEventListener('push', function(event) {
    let title = 'タスクの期限が近づいています！🚨';
    let options = {
        body: 'アプリを開いて今日の課題をチェックしよう！',
        icon: '/static/icon.png', // ホーム画面のアイコン画像
        badge: '/static/icon.png', // 通知バーに表示される小さなアイコン
        vibrate: [200, 100, 200]   // スマホをバイブレーションさせるパターン
    };

    // もしPythonサーバーから「具体的なタスク名」などのデータが送られてきたら書き換える
    if (event.data) {
        try {
            const data = event.data.json();
            title = data.title || title;
            options.body = data.body || options.body;
        } catch (e) {
            options.body = event.data.text();
        }
    }

    // スマホの画面に通知を表示する
    event.waitUntil(self.registration.showNotification(title, options));
});

// 🔔 通知がクリックされた時にアプリを開く処理
self.addEventListener('notificationclick', function(event) {
    event.notification.close(); // 通知を消す
    
    // アプリの画面（ホーム）を開く
    event.waitUntil(
        clients.openWindow('/')
    );
});