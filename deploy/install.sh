#!/usr/bin/env bash
# Установка сервиса контроля обещаний на чистый VPS (Ubuntu 22.04/24.04, Debian 12).
# Запуск от root:  bash install.sh
#
# Что делает:
#   1) ставит python3, venv, nginx
#   2) клонирует репозиторий в /opt/promise-control
#   3) создаёт venv и ставит зависимости
#   4) поднимает systemd-сервис на 127.0.0.1:8080
#   5) настраивает nginx как reverse proxy на 80 порт
#
# После установки сервис доступен по http://<IP-сервера>/
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/jabkamamka/promise-control.git}"
APP_DIR="/opt/promise-control"
PORT="${PORT:-8080}"

echo "== 1/5 пакеты"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git nginx

echo "== 2/5 код"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi

echo "== 3/5 окружение"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  cat > "$APP_DIR/.env" <<EOF
APP_TIMEZONE=Asia/Yekaterinburg
DATABASE_PATH=$APP_DIR/data/promises.db
AUTO_SEED=1
EOF
fi

echo "== 4/5 systemd"
cat > /etc/systemd/system/promise-control.service <<EOF
[Unit]
Description=Promise control service
After=network.target

[Service]
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable promise-control
systemctl restart promise-control

echo "== 5/5 nginx"
cat > /etc/nginx/sites-available/promise-control <<EOF
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/promise-control /etc/nginx/sites-enabled/promise-control
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

sleep 2
echo
echo "Готово. Проверка:"
curl -fsS "http://127.0.0.1:$PORT/health" || { echo "сервис не отвечает, смотри: journalctl -u promise-control -n 50"; exit 1; }
echo
echo "Открывай: http://$(curl -fsS https://api.ipify.org || echo '<IP>')/"
echo "Панель:   /"
echo "Аналитика: /analytics"
echo "Swagger:  /docs"
