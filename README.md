# Synology Surveillance Station -> Telegram 自动上传器

一个用 Python 写的守护进程：
- 轮询 Synology Surveillance Station 导出的监控目录
- 自动判断文件是否已经录制完成（文件大小稳定 + 最小文件年龄）
- 小文件用 `sendVideo` 上传（Telegram 内联可直接播放）
- 大文件用 `sendDocument` 上传（作为文件发送）

> 按你的要求，默认按 **2GB 以内**场景设计（Telegram Bot API 已支持大文件）。

---

## 1. 功能说明

### 录制完整性检测（避免上传正在写入的视频）
程序不会立刻上传新文件，而是做两层判断：
1. **大小稳定检查**：同一文件连续多次扫描大小不变（`STABLE_CHECKS_REQUIRED`）
2. **最小年龄检查**：文件最后修改时间距现在超过 `MIN_FILE_AGE_SEC`

两者都满足后才会上传，避免上传到一半的录像。

### Telegram 连接日志与重试
- 程序启动后会先调用 `getMe` 检测 Telegram 连通性，并打印连接日志。
- 若连接失败，会打印失败日志并按配置自动重试（`TELEGRAM_MAX_RETRIES` / `TELEGRAM_RETRY_DELAY_SEC`）。
- 上传过程中如果请求失败，也会自动重试并记录 warning 日志。

### 小文件/大文件自动选择上传方式
- 文件大小 `<= VIDEO_THRESHOLD_MB`：调用 Telegram `sendVideo`
- 文件大小 `> VIDEO_THRESHOLD_MB`：调用 Telegram `sendDocument`

你可以按网络和体验自己调阈值，比如 80MB / 200MB。

---

## 2. 目录结构

```text
.
├── app/main.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── scripts/build_image.sh
```

---

## 3. 本地运行

### 3.1 安装依赖
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3.2 设置环境变量
```bash
cp .env.example .env
# 编辑 .env
```

最少需要：
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `WATCH_DIR`

例如：
```bash
export TELEGRAM_BOT_TOKEN='123456:ABCDEF'
export TELEGRAM_CHAT_ID='-1001234567890'
export WATCH_DIR='/volume1/surveillance'
export ARCHIVE_DIR='/volume1/surveillance_uploaded'
python -m app.main
```

---

## 4. Docker 部署（你可直接用）

### 4.1 直接构建镜像（你要的编译脚本）
```bash
./scripts/build_image.sh
```

指定名字和 tag：
```bash
./scripts/build_image.sh my-uploader v1.0.0
```

### 4.2 用 docker compose 运行
```bash
cp .env.example .env
# 填好 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
docker compose up -d --build
```

> 注意把 `docker-compose.yml` 里的卷路径改成你 NAS 的真实路径。

---

## 5. 环境变量

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `TELEGRAM_BOT_TOKEN` | 无 | Telegram Bot Token（必填） |
| `TELEGRAM_CHAT_ID` | 无 | 接收消息的 chat/channel id（必填） |
| `WATCH_DIR` | `/data/surveillance` | 监控视频目录 |
| `ARCHIVE_DIR` | 空 | 上传后移动到该目录；为空则删除原文件 |
| `POLLING_INTERVAL_SEC` | `15` | 扫描间隔秒数 |
| `STABLE_CHECKS_REQUIRED` | `3` | 连续稳定次数 |
| `MIN_FILE_AGE_SEC` | `30` | 最小文件年龄（秒） |
| `VIDEO_THRESHOLD_MB` | `80` | 小文件阈值（MB） |
| `VIDEO_EXTENSIONS` | `.mp4,.mkv,.avi,.mov` | 扫描扩展名 |
| `RECURSIVE_SCAN` | `true` | 是否递归扫描子目录 |
| `TELEGRAM_MAX_RETRIES` | `5` | Telegram 连接/上传最大重试次数 |
| `TELEGRAM_RETRY_DELAY_SEC` | `5` | 每次重试前等待秒数 |
| `HTTP_TIMEOUT` | `180` | Telegram 上传超时时间（秒） |
| `LOG_LEVEL` | `INFO` | 日志级别 |

---

## 6. 运行逻辑建议

1. Surveillance Station 输出目录建议挂载为只读（`/data/in:ro`）。
2. `ARCHIVE_DIR` 使用单独目录，方便二次备份/清理。
3. 若你发现仍有“刚写完就上传失败”，把：
   - `MIN_FILE_AGE_SEC` 调大到 60~120
   - `STABLE_CHECKS_REQUIRED` 调大到 4~6

---

## 7. 常见问题

### Q1: 为什么有些视频发送成“文件”了？
因为超过了 `VIDEO_THRESHOLD_MB`，这是你要求的逻辑。调大即可。

### Q2: 上传后原视频会怎样？
- 设置 `ARCHIVE_DIR`：移动过去
- 不设置：默认删除

### Q3: 单文件最大支持多少？
你说的视频不会超过 2GB，这个项目按该上限使用场景设计。
