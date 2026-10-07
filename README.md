# x2link-lite

リンクを作成・整理し、公開後の転送先変更・停止・反応確認を行う軽量構成です。x2link-newから分離した独立Gitリポジトリで、SQLiteを唯一のデータベースとして使用します。Docker、PostgreSQL、Python仮想環境は使いません。

## 必要なもの

- Linuxサーバー（1〜2 vCPU、メモリ1 GB以上を目安）
- Python 3.12以上とpip（OSのパッケージ管理で導入）
- HTTPSを終端するNginx等のリバースプロキシ
- データベースとバックアップを置く永続ディスク

## インストールと初回設定

OSが提供するPython環境へ依存パッケージをインストールします。Debian/Ubuntuでは、ディストリビューションのPythonパッケージを使う方法を推奨します。pipを直接使う場合、OSの外部管理Pythonへのインストールを許す環境でのみ実行してください。

```sh
sudo apt install python3 python3-pip
sudo pip3 install -r requirements.txt
sudo install -d -o www-data -g www-data -m 750 /var/lib/x2link
```

本番用の秘密鍵を生成して環境変数 `X2LINK_SECRET_KEY` に設定してください。`X2LINK_DB_PATH` は `/var/lib/x2link/db.sqlite3` のような永続ディスク上のパスにします。`X2LINK_DEBUG=0`、`X2LINK_ALLOWED_HOSTS`、`X2LINK_ADMIN_HOST`、`X2LINK_PUBLIC_ORIGIN`、`X2LINK_SUPPORT_EMAIL` も設定します。秘密鍵をGitやシェル履歴へ保存しないでください。

```sh
sudo -u www-data env X2LINK_DB_PATH=/var/lib/x2link/db.sqlite3 python3 manage.py migrate
sudo -u www-data env X2LINK_DB_PATH=/var/lib/x2link/db.sqlite3 python3 manage.py setup_operator --username operator
sudo -u www-data python3 manage.py collectstatic --noinput
```

管理者パスワードは対話入力します。初回ログイン後に認証アプリと回復コードを設定してください。公開前のDNS検査には外部DNSへの接続が必要です。

## 起動

アプリはGunicornで起動し、Nginx等のHTTPSリバースプロキシの背後に置いてください。Gunicornとワーカーは同じ設定環境変数を使います。

```sh
sudo -u www-data env X2LINK_DEBUG=0 X2LINK_SECRET_KEY='設定した秘密鍵' X2LINK_DB_PATH=/var/lib/x2link/db.sqlite3 X2LINK_ALLOWED_HOSTS='admin.example.com,go.example.com' X2LINK_ADMIN_HOST=admin.example.com X2LINK_PUBLIC_ORIGIN=https://go.example.com X2LINK_SUPPORT_EMAIL=ops@example.com X2LINK_TRUST_PROXY=1 gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 30
```

本番では上記プロセスをsystemd等のサービス管理下で起動し、自動再起動を設定してください。別の常駐プロセスとして `python3 manage.py run_worker` を1つ起動します。SQLiteは単一サーバー・低〜中程度の書き込み量を想定します。複数サーバーから同じDBファイルを共有したり、ワーカーを複数起動したりしないでください。

Nginxの設定例は `deploy/nginx.conf` を参照し、ドメイン・証明書・静的ファイルのパスを環境に合わせてください。管理画面と公開転送のホストを分け、HTTPSを必須にします。

## 定期処理とバックアップ

`run_worker` が毎分のクリック集計と日次の期限処理を行います。DBとバックアップはWebプロセスの実行ユーザーだけが読める権限にし、バックアップを別ディスクまたは別ホストへ定期コピーしてください。

```sh
sudo -u www-data python3 manage.py backup_database /var/backups/x2link/snapshot.sqlite3
sudo -u www-data python3 manage.py restore_database /var/backups/x2link/snapshot.sqlite3 --output /var/lib/x2link/restored.sqlite3
```

詳細イベントは30日、日次集計は397日、監査記録は180日、任意保存した本文結果は7日保持します。SQLiteのバックアップと復元は `sqlite3` のオンラインバックアップAPIを利用します。

## 開発者向け確認

```sh
python3 -m pip install -r requirements-dev.txt
python3 manage.py test links.tests
python3 manage.py check
python3 manage.py makemigrations --check --dry-run
```

ブラウザー検証と負荷検証は開発用依存を追加して実行してください。Lite版はSQLiteの単一サーバー構成に絞っています。
