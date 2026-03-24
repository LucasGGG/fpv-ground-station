# FPV Remote Ground Station

Система віддаленого керування FPV дроном через інтернет.

**Стек:** Raspberry Pi 4 · TBS RapidFire · ELRS 900 MHz · WireGuard VPN · Starlink · Telegram Bot

---

## Архітектура

```
Дрон (VTX 5.8GHz аналог)
    │
    ▼
TBS RapidFire VRX  (AV OUT)
    │
    ▼
USB Capture Card (MS2109)
    │  USB
    ▼
Raspberry Pi 4 ──────────────────────────────────────────────────────
│                                                                    │
│  video_stream.service     rc_control.service                       │
│  GStreamer pipeline        UDP → CRSF bridge                       │
│  v4l2src → x264enc         /dev/serial0 @ 420000 baud             │
│  → RTP UDP :5600           → Nomad TX (ELRS 900)                  │
│                                                                    │
│  WireGuard VPN (fpv0)     Telegram Bot                            │
│  10.0.0.1/24              моніторинг, керування, записи           │
└─────────────────────────────────────────────────────────────────── │
         │ Starlink                                                   │
         ▼                                                            │
   [ Інтернет ]                                                       │
         │                                                            │
         ▼                                                            ▼
   Оператор (Mac)                                            Nomad TX → ELRS RX → Дрон
   10.0.0.2/24
   ffplay / GStreamer
   rc_sender.py + Boxer
```

---

## Залізо

| Компонент | Модель |
|---|---|
| Комп'ютер | Raspberry Pi 4 Model B 4GB |
| VRX | TBS RapidFire |
| Capture Card | MS2109 USB (UVC) |
| TX Module | RadioMaster Nomad (ELRS 900 MHz) |
| Інтернет | Starlink |
| Живлення | 4S LiPo + DC-DC 5V/5A |
| Пульт оператора | RadioMaster Boxer |

---

## Структура проєкту

```
├── pi/
│   ├── scripts/
│   │   ├── video_stream.sh        # GStreamer: capture → H264 → RTP UDP
│   │   ├── rc_control.py          # UDP пакети → CRSF → UART
│   │   ├── crsf.py                # CRSF протокол (16ch, CRC8-DVB-S2)
│   │   ├── tg_bot.py              # Telegram бот керування
│   │   ├── video_server.py        # HTTP сервер для відеозаписів
│   │   └── watchdog_heartbeat.py  # Heartbeat для STM32 (опціонально)
│   ├── services/
│   │   ├── video_stream.service
│   │   ├── rc_control.service
│   │   ├── vpn.service
│   │   ├── tg_bot.service
│   │   ├── video_server.service
│   │   ├── fpv_cleanup.service
│   │   └── fpv_cleanup.timer
│   ├── config/
│   │   └── fpv.env                # Змінні середовища
│   └── setup_pi.sh                # Автоматичне встановлення
│
├── operator/
│   ├── rc_sender.py               # Джойстик → UDP пакети → Pi
│   ├── video_receive.sh           # ffplay / GStreamer RTP приймач
│   └── fpv.sdp                    # SDP для ffplay
│
└── stm32/
    └── fpv_watchdog.c             # Watchdog firmware (опціонально)
```

---

## Швидкий старт

### 1. Raspberry Pi

```bash
# Скопіювати проєкт на Pi
rsync -av pi/ pi@<PI_IP>:/home/pi/fpv/

# Запустити setup
ssh pi@<PI_IP>
sudo bash /home/pi/fpv/setup_pi.sh
```

Після setup скрипт виведе **публічний ключ Pi** — збережи його.

### 2. Конфігурація WireGuard

**На Pi** (`/etc/wireguard/fpv0.conf`):
```ini
[Interface]
PrivateKey = <згенерований setup скриптом>
Address = 10.0.0.1/24
ListenPort = 51821

[Peer]
PublicKey = <публічний ключ оператора>
Endpoint = <публічний IP оператора>:51820
AllowedIPs = 10.0.0.2/32
PersistentKeepalive = 25
```

**На операторському ПК** (`operator/fpv0_operator.conf`):
```ini
[Interface]
PrivateKey = <приватний ключ оператора>
Address = 10.0.0.2/24
ListenPort = 51820

[Peer]
PublicKey = <публічний ключ Pi>
AllowedIPs = 10.0.0.1/32
Endpoint = 10.0.0.1:51821
PersistentKeepalive = 25
```

### 3. Генерація ключів оператора

```bash
wg genkey | tee operator_private.key | wg pubkey > operator_public.key
```

### 4. Запуск VPN на Mac

```bash
sudo /opt/homebrew/bin/bash /opt/homebrew/bin/wg-quick up operator/fpv0_operator.conf
```

### 5. Отримання відео

```bash
ffplay -protocol_whitelist file,udp,rtp,crypto \
       -i operator/fpv.sdp \
       -fflags nobuffer -flags low_delay -framedrop \
       -probesize 32 -analyzeduration 0
```

### 6. RC керування (джойстик)

```bash
pip3 install pygame
PI_HOST=10.0.0.1 python3 operator/rc_sender.py
```

---

## Змінні середовища (`/etc/fpv/fpv.env`)

| Змінна | За замовчуванням | Опис |
|---|---|---|
| `OPERATOR_HOST` | `10.0.0.2` | IP оператора (VPN) |
| `VIDEO_PORT` | `5600` | UDP порт відео |
| `RC_UDP_PORT` | `5601` | UDP порт RC команд |
| `VIDEO_DEVICE` | `/dev/video0` | Capture card |
| `UART_PORT` | `/dev/serial0` | UART для CRSF |
| `UART_BAUD` | `420000` | Швидкість UART |
| `CRSF_HZ` | `100` | Частота CRSF кадрів |

---

## Telegram Bot

Бот відправляє повідомлення при запуску Pi та зміні IP.

Команди: `/start` `/status` `/ip`

**Вкладки:**

| Кнопка | Функція |
|---|---|
| 📊 Статус | Сервіси, IP, CPU, RAM, температура, диск |
| 🔧 Сервіси | Старт / Стоп / Рестарт кожного сервісу |
| 📡 VPN | Endpoint, рестарт, ping оператора |
| 📋 Логи | journalctl по сервісах + журнал дій |
| 🖥 Термінал | Shell команди прямо з Telegram |
| 🌐 Мережа | Ping, Starlink статус, скріншот |
| 📈 Графіки | CPU температура і ping за годину |
| 📹 Відео | Запис ON/OFF, список, посилання на завантаження |
| ⚙️ Конфіг | Перегляд і редагування fpv.env |
| 🔴 Kill Switch | Миттєво вимкнути всі сервіси |
| ⏹ Shutdown | Безпечне вимкнення з відліком |
| ⚡ Reboot | Перезавантаження з підтвердженням |

**Автоматичні сповіщення:**
- Зміна IP адреси
- CPU температура > 80°C
- Диск заповнений > 90%
- Втрата / відновлення інтернету

---

## Відео HTTP сервер

Записи доступні за адресою:
```
http://10.0.0.1:8080
```
Автоматично видаляє файли старше 3 днів (systemd timer).

---

## CRSF протокол

- 16 каналів × 11 біт = 22 байти payload
- CRC8-DVB-S2 (poly 0xD5)
- Кадр: `[0xC8][len][0x16][22 bytes][crc]` = 26 байт
- Failsafe: throttle → 1000 мкс після 1 сек без пакетів

---

## UDP пакет RC (оператор → Pi)

```
[0x52 0x43] [ch0..ch15 uint16 LE × 16] [checksum uint16 LE]
Всього: 36 байт
Значення каналів: 1000–2000 мкс
```

---

## Цілі затримки

| Параметр | Ціль |
|---|---|
| Загальна затримка відео | < 400 мс |
| Encoder | x264 ultrafast/zerolatency |
| Бітрейт | 800–1500 кбіт/с |
| Роздільна здатність | 720×480 @ 30fps |
| RC частота | 50–100 Гц |

---

## Ліцензія

Private repository — всі права захищені.
