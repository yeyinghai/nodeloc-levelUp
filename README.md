# NodeLoc 自动升级脚本 v4.0

> 支持 **青龙面板** 和 **GitHub Actions** 双平台。

## 📁 文件结构

```
├── nodeloc_upgrade_selenium.py   # 主脚本（v4.0 混合 API + Selenium）
├── .github/workflows/nodeloc.yml # GitHub Actions 工作流
└── README.md
```

---

## 🔍 v4.0 优化内容（基于对网站的实际分析）

| 功能 | v3.x | v4.0 |
|------|------|------|
| 签到 | Selenium 点击 | Selenium 点击（nonce 由前端 JS 生成，必须保留）|
| 浏览话题 | Selenium 逐页滚动 | `GET /latest.json` 纯 API |
| 标记已读 | 等待页面滚动 | `POST /topics/timings` 纯 API |
| 点赞 | Selenium 查找按钮 | `POST /post_actions` 标准 Discourse API |
| 回复 | Selenium 填写编辑器 | `POST /posts` 标准 Discourse API |
| 话题 URL | `/t/slug/id`（slug 获取有误） | `/t/{id}`（正确格式）|
| 签到检测 | 检查 title 文字 | 检查 `class=checked-in`（更准确）|
| 速度 | 慢（全靠浏览器等待）| **快 5~10 倍**（API 直接调用）|
| 资源 | Chrome 全程运行 | **Chrome 仅签到时启动，完成后立即关闭** |

---

## 🚀 GitHub Actions 部署

### 第一步：配置 Secrets

仓库 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | 说明 | 必填 |
|--------|------|------|
| `NODELOC_USERNAME` | 登录用户名 | ✅ |
| `NODELOC_PASSWORD` | 登录密码 | ✅ |
| `TG_BOT_TOKEN` | Telegram Bot Token | 可选 |
| `TG_CHAT_ID` | Telegram Chat ID | 可选 |
| `GOTIFY_URL` | Gotify 服务器 | 可选 |
| `GOTIFY_TOKEN` | Gotify Token | 可选 |
| `SC3_PUSH_KEY` | Server 酱³ SendKey | 可选 |
| `WECHAT_API_URL` | 自定义微信 API | 可选 |
| `WECHAT_AUTH_TOKEN` | 微信 API Token | 可选 |
| `NODELOC_PROXY` | HTTP 代理（如需） | 可选 |

### 第二步：开启 Actions

仓库 → **Actions** → Enable workflows

### 第三步：手动验证

Actions → **NodeLoc 自动升级** → Run workflow

---

## ⏰ 定时规则

| 触发时间（北京）| Cron（UTC）|
|----------------|-----------|
| 早上 09:00 | `0 1 * * *` |
| 晚上 21:00 | `0 13 * * *` |

---

## ⚙️ 任务量配置（可通过环境变量或 Secrets 设置）

```
NL_TOPICS=30   # 每日浏览话题数（默认 30）
NL_LIKES=15    # 每日点赞数（默认 15）
NL_REPLIES=5   # 每日回复数（默认 5）
```

---

## 🏠 青龙面板部署

```bash
# 安装依赖
pip3 install loguru curl-cffi selenium

# 系统依赖（Debian 镜像）
apt-get update && apt-get install -y chromium chromium-driver
```

> ⚠️ 请使用 `whyour/qinglong:debian` 镜像

定时任务命令：`task /ql/data/scripts/nodeloc_upgrade_selenium.py`  
定时规则：`0 9,21 * * *`

---

**作者**：djkyc ｜ **版本**：4.0.0 ｜ 仅供技术学习交流
