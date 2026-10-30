# Деплой на российский хостинг (без VPN)

Сервис — обычное Python-приложение (FastAPI + SQLite), поэтому подходит любой VPS
или PaaS с Docker. Ниже — варианты, которые открываются из РФ без VPN.

## Что нужно от владельца

Любой из вариантов требует **аккаунт хостинга** — его создаёт владелец (почта, телефон,
иногда карта РФ). После этого сервис ставится одной командой.

## Вариант 1. VPS (Timeweb Cloud, Beget, Reg.ru, VK Cloud, Yandex Cloud)

Самый предсказуемый и дешёвый: VPS от ~200 ₽/мес, российские IP, без блокировок.

1. Создать VPS: Ubuntu 22.04/24.04, 1 vCPU, 1 ГБ RAM, публичный IPv4.
2. Зайти по SSH и выполнить:

```bash
curl -fsSL https://raw.githubusercontent.com/jabkamamka/promise-control/main/deploy/install.sh -o install.sh
bash install.sh
```

Скрипт поставит Python, nginx, systemd-сервис и запустит его.
Через минуту сайт доступен по `http://<IP-сервера>/`.

Обновление после изменений в репозитории:

```bash
cd /opt/promise-control && git pull && systemctl restart promise-control
```

Домен и HTTPS (если есть домен):

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d your-domain.ru
```

## Вариант 2. Docker (любой PaaS с российским регионом)

```bash
docker build -t promise-control .
docker run -d -p 80:8080 --name promise promise-control
```

`Dockerfile` уже в репозитории, `AUTO_SEED=1` подгружает снимок звонков из API
при пустой базе.

## Вариант 3. Публичный туннель с ноутбука (быстро, но зависит от ПК)

Если сервер не нужен прямо сейчас: российский сервис туннелей CloudPub
(<https://cloudpub.ru>) даёт постоянный адрес на бесплатном тарифе и не блокируется в РФ.

```powershell
# на компьютере, где запущен сервис
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
# в другом окне — по инструкции CloudPub подключить проброс на 8080
```

Минус: адрес работает, только пока включён компьютер.

## Что важно знать

- **Данные.** Бесплатные тарифы дают эфемерный диск: SQLite обнуляется при перезапуске.
  `AUTO_SEED=1` заново загружает снимок звонков из API. Для постоянного хранения нужен
  диск (на VPS это просто файл на диске) или PostgreSQL.
- **Память.** Сервису хватает 256–512 МБ RAM.
- **Порт.** Приложение слушает `$PORT` (по умолчанию 8080) и `0.0.0.0` в контейнере.
