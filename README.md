# NodeLoc 自动升级脚本 

> 支持 **青龙面板** 和 **GitHub Actions** 双平台。

## 📁 文件结构

```
├── nodeloc_upgrade_selenium.py   # 主脚本（混合 API + Selenium）
├── .github/workflows/nodeloc.yml # GitHub Actions 工作流
└── README.md
```


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

## 运行结果展示

#### 1、签到和点赞

![360截图20260312231749174](https://github.com/user-attachments/assets/88f85363-2a6a-411d-bd16-9e6889f5f590)

#### 2、话题回复

![360截图20260312231823509](https://github.com/user-attachments/assets/6c944f21-7b99-4bc8-b6cb-4bc1c0fee84a)

#### 3、任务完成统计

![360截图20260312231856053](https://github.com/user-attachments/assets/bc2158e1-d25e-484c-bb5e-918285ced8bb)

---
脚本是从djkyc的脚本升级更新而来，原脚本仓库地址：[djky/cnodeloc](https://github.com/djkyc/nodeloc)

感谢大神的开源精神！！
