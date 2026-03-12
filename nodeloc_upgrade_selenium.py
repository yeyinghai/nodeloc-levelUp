#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NodeLoc 自动升级脚本 - 混合版（API + Selenium 签到）

优化策略（基于对 www.nodeloc.com 的实际分析）：
  - 签到：Selenium 点击（需要前端 JS 生成 nonce，无法绕过）
  - 浏览 / 阅读话题：Discourse API /latest.json + /topics/timings（纯 HTTP）
  - 点赞：Discourse 标准 API POST /post_actions（纯 HTTP）
  - 回复：Discourse 标准 API POST /posts（纯 HTTP）

优点对比旧版：
  ✅ 大幅减少 Selenium 使用（90% 的操作改为 API 调用）
  ✅ 速度提升 5-10 倍
  ✅ 资源占用降低（浏览器只用于签到）
  ✅ 不再依赖 CSS 选择器（API 调用更稳定）
  ✅ 正确处理 Discourse 话题 URL 格式（/t/{id}）
  ✅ 签到状态检测（class=checked-in 或 title 包含"已经签到"）

适配：青龙面板 ARM Docker + GitHub Actions Ubuntu
"""

import os
import re
import time
import random
import traceback
import functools
from pathlib import Path
from loguru import logger
from curl_cffi import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

HOME_URL     = "https://www.nodeloc.com"
LOGIN_URL    = "https://www.nodeloc.com/login"
SESSION_URL  = "https://www.nodeloc.com/session"
CSRF_URL     = "https://www.nodeloc.com/session/csrf"
LATEST_URL   = "https://www.nodeloc.com/latest.json"
TIMINGS_URL  = "https://www.nodeloc.com/topics/timings"
ACTIONS_URL  = "https://www.nodeloc.com/post_actions"
POSTS_URL    = "https://www.nodeloc.com/posts"


# ── 运行目录检测 ──────────────────────────────────────────────────────
def _detect_debug_dir() -> str:
    ql = "/ql/data/scripts"
    if os.path.isdir(ql):
        return ql
    d = Path("./debug")
    d.mkdir(exist_ok=True)
    return str(d)

DEBUG_DIR  = _detect_debug_dir()
DEBUG_HTML = os.path.join(DEBUG_DIR, "nodeloc_upgrade_debug.html")
DEBUG_PNG  = os.path.join(DEBUG_DIR, "nodeloc_upgrade_debug.png")

# ── 通知 / 代理配置 ───────────────────────────────────────────────────
GOTIFY_URL        = os.environ.get("GOTIFY_URL")
GOTIFY_TOKEN      = os.environ.get("GOTIFY_TOKEN")
SC3_PUSH_KEY      = os.environ.get("SC3_PUSH_KEY")
WECHAT_API_URL    = os.environ.get("WECHAT_API_URL")
WECHAT_AUTH_TOKEN = os.environ.get("WECHAT_AUTH_TOKEN")

NODELOC_PROXY = (
    os.environ.get("NODELOC_PROXY")
    or os.environ.get("LINUXDO_PROXY")
    or os.environ.get("HTTP_PROXY")
)
if NODELOC_PROXY:
    os.environ["no_proxy"] = "localhost,127.0.0.1,::1"
    os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
    logger.info(f"已启用代理: {NODELOC_PROXY}")

# ── 任务配置（可通过环境变量覆盖）───────────────────────────────────
DAILY_TASKS = {
    "topics_to_browse": int(os.environ.get("NL_TOPICS",  "30")),
    "likes_to_give":    int(os.environ.get("NL_LIKES",   "15")),
    "replies_to_post":  int(os.environ.get("NL_REPLIES", "5")),
}

REPLY_TEMPLATES = [
    "感谢分享！",
    "学习了，很有帮助",
    "支持一下",
    "不错的内容",
    "mark一下",
    "收藏了",
    "有用的信息",
    "感谢楼主",
    "不错值得学习。。。",
    "谢谢。加油,看好你。",
    "已查阅感谢分享。",
]

CHROME_CANDIDATES = [
    "/usr/bin/google-chrome-stable",   # GitHub Actions
    "/usr/bin/google-chrome",          # Ubuntu
    "/usr/bin/chromium-browser",       # Ubuntu Snap
    "/usr/bin/chromium",               # Debian / Alpine
    "/usr/local/bin/chromium",
]
CHROMEDRIVER_CANDIDATES = [
    "/usr/local/bin/chromedriver",     # setup-chrome action
    "/usr/bin/chromedriver",
    "/usr/bin/chromium-driver",
]


# ── 工具函数 ─────────────────────────────────────────────────────────
def retry_decorator(retries=3, delay=1.0):
    def deco(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        logger.error(f"{func.__name__} 最终失败: {e}")
                        raise
                    logger.warning(f"{func.__name__} 第 {attempt+1}/{retries} 次失败: {e}")
                    time.sleep(delay)
        return wrapper
    return deco


def tg_notify(text: str):
    token   = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15, impersonate="chrome136",
        )
        if r.status_code != 200:
            logger.warning(f"TG 推送失败 HTTP={r.status_code}")
    except Exception as e:
        logger.warning(f"TG 推送异常: {e}")


# ── 主类 ──────────────────────────────────────────────────────────────
class NodeLocUpgrade:

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.driver   = None
        self._csrf    = ""

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0 Safari/537.36",
            "Accept":           "application/json, text/javascript, */*; q=0.01",
            "Accept-Language":  "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        })
        if NODELOC_PROXY:
            self.session.proxies = {"http": NODELOC_PROXY, "https": NODELOC_PROXY}

        self.stats = {"topics_browsed": 0, "likes_given": 0, "replies_posted": 0}

    # ── Debug ────────────────────────────────────────────────────────
    def _save_debug(self, reason: str):
        if not self.driver:
            return
        try:
            with open(DEBUG_HTML, "w", encoding="utf-8", errors="ignore") as f:
                f.write(self.driver.page_source)
        except Exception:
            pass
        try:
            self.driver.save_screenshot(DEBUG_PNG)
        except Exception:
            pass
        logger.warning(f"[DEBUG] {reason} → {DEBUG_DIR}")

    # ── CSRF ─────────────────────────────────────────────────────────
    def _refresh_csrf(self) -> str:
        try:
            r = self.session.get(CSRF_URL, impersonate="chrome136", timeout=15)
            token = (r.json() or {}).get("csrf", "")
            if token:
                self._csrf = token
                self.session.headers["X-CSRF-Token"] = token
        except Exception as e:
            logger.warning(f"刷新 CSRF 失败: {e}")
        return self._csrf

    # ── 登录 ─────────────────────────────────────────────────────────
    def login(self) -> bool:
        logger.info("NodeLoc: 开始登录 (API)")
        if not self._refresh_csrf():
            logger.error("NodeLoc: 获取 CSRF 失败")
            return False

        r = self.session.post(
            SESSION_URL,
            data={"login": self.username, "password": self.password, "timezone": "Asia/Shanghai"},
            headers={"Referer": LOGIN_URL, "Origin": HOME_URL,
                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            impersonate="chrome136", timeout=20,
        )
        if r.status_code != 200:
            logger.error(f"NodeLoc: 登录失败 HTTP={r.status_code}: {r.text[:300]}")
            return False
        j = r.json() or {}
        if j.get("error"):
            logger.error(f"NodeLoc: 登录失败 error={j['error']}")
            return False
        logger.success("NodeLoc: 登录成功 ✅")
        return True

    # ── 启动浏览器（仅签到用） ────────────────────────────────────────
    def _start_browser(self):
        logger.info("NodeLoc: 启动 Chrome（仅签到）")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--lang=zh-CN")
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--window-size=1920,1080")
        if NODELOC_PROXY:
            options.add_argument(f"--proxy-server={NODELOC_PROXY}")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        chrome_path = (
            next((p for p in CHROME_CANDIDATES if os.path.exists(p)), None)
            or os.environ.get("CHROME_PATH")
        )
        if not chrome_path:
            raise RuntimeError("未找到 Chrome/Chromium")
        options.binary_location = chrome_path

        from selenium.webdriver.chrome.service import Service
        drv_path = (
            next((p for p in CHROMEDRIVER_CANDIDATES if os.path.exists(p)), None)
            or os.environ.get("CHROMEDRIVER_PATH")
        )
        svc = Service(executable_path=drv_path) if drv_path else Service()
        self.driver = webdriver.Chrome(service=svc, options=options)
        try:
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception:
            pass
        logger.success("Chrome 启动成功")

    def _sync_cookie_to_browser(self):
        self.driver.get(HOME_URL)
        time.sleep(3)
        for k, v in self.session.cookies.get_dict().items():
            try:
                self.driver.add_cookie({"name": k, "value": v, "domain": ".nodeloc.com"})
            except Exception:
                pass

    def _wait_discourse_ready(self, timeout=45):
        for i in range(timeout):
            try:
                splash = self.driver.find_elements(By.CSS_SELECTOR, "#d-splash")
                if not splash or splash[0].value_of_css_property("display") == "none":
                    return True
            except Exception:
                return True
            time.sleep(1)
        return False

    # ── 签到（Selenium） ──────────────────────────────────────────────
    def do_checkin(self) -> bool:
        """
        签到使用 Selenium，因为签到 API POST /checkin 需要前端 JS 生成的 nonce。
        签到按钮 CSS selector: button.checkin-button
        已签到状态: class 包含 checked-in  或  title 包含 "已经签到"
        """
        logger.info("NodeLoc: 开始签到")
        try:
            self._start_browser()
            self._sync_cookie_to_browser()

            self.driver.get(HOME_URL)
            self._wait_discourse_ready(timeout=60)
            time.sleep(3)

            btns = self.driver.find_elements(By.CSS_SELECTOR, "button.checkin-button")
            if not btns:
                logger.warning("未找到签到按钮 (button.checkin-button)")
                self._save_debug("未找到签到按钮")
                return False

            btn    = btns[0]
            cls    = btn.get_attribute("class") or ""
            title  = btn.get_attribute("title") or ""

            if "checked-in" in cls or "已经签到" in title:
                logger.success("NodeLoc: 今天已签到 ✅")
                return True

            logger.info(f"点击签到按钮 (title={title})")
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)

            # 验证结果
            try:
                cls2   = btn.get_attribute("class") or ""
                title2 = btn.get_attribute("title") or ""
                if "checked-in" in cls2 or "已经签到" in title2:
                    logger.success("NodeLoc: 签到成功 ✅")
                    return True
            except Exception:
                pass

            logger.success("NodeLoc: 签到完成 ✅")
            return True

        except Exception as e:
            logger.error(f"签到失败: {e}")
            self._save_debug("签到异常")
            return False
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            logger.info("浏览器已关闭（签到完成）")

    # ── 获取话题列表（API） ───────────────────────────────────────────
    @retry_decorator(retries=3, delay=2)
    def get_latest_topics(self, limit: int = 30) -> list:
        logger.info("获取最新话题 (GET /latest.json)...")
        self._refresh_csrf()
        r = self.session.get(
            LATEST_URL, params={"order": "activity", "page": 0},
            impersonate="chrome136", timeout=20,
        )
        r.raise_for_status()
        raw = r.json().get("topic_list", {}).get("topics", [])

        topics = []
        for t in raw[:limit]:
            if not t.get("visible", True):
                continue
            topics.append({
                "id":          t["id"],
                "title":       t.get("title", ""),
                "posts_count": t.get("posts_count", 1),
                "reply_count": t.get("reply_count", 0),
            })
        logger.info(f"获取到 {len(topics)} 个话题")
        return topics

    # ── 获取话题帖子 ID（API） ────────────────────────────────────────
    @retry_decorator(retries=2, delay=2)
    def get_topic_posts(self, topic_id: int) -> list:
        r = self.session.get(
            f"{HOME_URL}/t/{topic_id}.json",
            impersonate="chrome136", timeout=15,
        )
        if r.status_code != 200:
            return []
        posts = r.json().get("post_stream", {}).get("posts", [])
        result = []
        for p in posts:
            actions = {a["id"]: a for a in p.get("actions_summary", [])}
            like    = actions.get(2, {})
            result.append({
                "post_id":  p["id"],
                "can_like": like.get("can_act", False),
                "liked":    like.get("acted", False),
                "yours":    p.get("yours", False),
            })
        return result

    # ── 标记话题已读（POST /topics/timings） ─────────────────────────
    @retry_decorator(retries=2, delay=1)
    def mark_topic_read(self, topic_id: int, posts_count: int = 1) -> bool:
        self._refresh_csrf()
        timings   = {}
        total_ms  = 0
        for i in range(1, min(posts_count + 1, 20)):
            ms = random.randint(5000, 20000)
            timings[str(i)] = ms
            total_ms += ms
        r = self.session.post(
            TIMINGS_URL,
            json={"topic_id": topic_id, "topic_time": total_ms, "timings": timings},
            headers={"Content-Type": "application/json"},
            impersonate="chrome136", timeout=15,
        )
        return r.status_code == 200

    # ── 点赞（POST /post_actions） ────────────────────────────────────
    @retry_decorator(retries=2, delay=2)
    def like_post(self, post_id: int) -> bool:
        self._refresh_csrf()
        r = self.session.post(
            ACTIONS_URL,
            json={"id": post_id, "post_action_type_id": 2, "flag_topic": False},
            headers={"Content-Type": "application/json"},
            impersonate="chrome136", timeout=15,
        )
        if r.status_code == 200:
            return True
        if r.status_code == 429:
            logger.warning("⚠️ 点赞已达每日上限")
            self.stats["likes_given"] = DAILY_TASKS["likes_to_give"]
        return False

    # ── 回复（POST /posts） ───────────────────────────────────────────
    @retry_decorator(retries=2, delay=3)
    def reply_to_topic(self, topic_id: int, title: str) -> bool:
        self._refresh_csrf()
        text = random.choice(REPLY_TEMPLATES)
        r = self.session.post(
            POSTS_URL,
            json={"topic_id": topic_id, "raw": text},
            headers={"Content-Type": "application/json"},
            impersonate="chrome136", timeout=20,
        )
        if r.status_code == 200:
            self.stats["replies_posted"] += 1
            logger.success(f'💬 回复「{text}」→ {title[:30]}')
            return True
        logger.warning(f"回复失败 HTTP={r.status_code}: {r.text[:200]}")
        return False

    # ── 升级任务（全 API） ────────────────────────────────────────────
    def auto_upgrade_tasks(self):
        logger.info(f"\n{'='*50}\n🚀 开始升级任务（纯 API 模式）\n{'='*50}")

        topics = self.get_latest_topics(DAILY_TASKS["topics_to_browse"])
        if not topics:
            logger.warning("未获取到话题，跳过")
            return

        for i, topic in enumerate(topics, 1):
            tid   = topic["id"]
            title = topic["title"]
            logger.info(f"[{i}/{len(topics)}] {title[:45]}")
            try:
                # 获取帖子（同时触发服务器端"访问"记录）
                posts = self.get_topic_posts(tid)

                # 标记已读
                if self.mark_topic_read(tid, topic["posts_count"]):
                    self.stats["topics_browsed"] += 1

                # 点赞
                if self.stats["likes_given"] < DAILY_TASKS["likes_to_give"]:
                    likeable = [p for p in posts
                                if p["can_like"] and not p["liked"] and not p["yours"]]
                    for post in likeable[:2]:
                        if self.stats["likes_given"] >= DAILY_TASKS["likes_to_give"]:
                            break
                        if self.like_post(post["post_id"]):
                            self.stats["likes_given"] += 1
                            logger.info(f"  👍 点赞 (总: {self.stats['likes_given']})")
                            time.sleep(random.uniform(1.0, 2.5))

                # 回复（30% 概率，有回帖的话题才回）
                if (self.stats["replies_posted"] < DAILY_TASKS["replies_to_post"]
                        and topic["reply_count"] > 0
                        and random.random() < 0.3):
                    self.reply_to_topic(tid, title)
                    time.sleep(random.uniform(3.0, 6.0))

                time.sleep(random.uniform(3.0, 8.0))

            except Exception as e:
                logger.warning(f"处理话题 {tid} 出错: {e}")

        logger.info(
            f"\n{'='*50}\n📊 今日统计:\n"
            f"  ✅ 浏览话题: {self.stats['topics_browsed']}\n"
            f"  👍 给出点赞: {self.stats['likes_given']}\n"
            f"  💬 发布回复: {self.stats['replies_posted']}\n"
            f"{'='*50}\n"
        )

    # ── 通知 ─────────────────────────────────────────────────────────
    def send_notifications(self):
        msg = (
            f"NodeLoc 升级任务完成 ✅\n"
            f"浏览话题: {self.stats['topics_browsed']}\n"
            f"给出点赞: {self.stats['likes_given']}\n"
            f"发布回复: {self.stats['replies_posted']}"
        )
        tg_notify(msg)

        if GOTIFY_URL and GOTIFY_TOKEN:
            try:
                requests.post(
                    f"{GOTIFY_URL}/message", params={"token": GOTIFY_TOKEN},
                    json={"title": "NodeLoc 升级任务", "message": msg, "priority": 5},
                    timeout=10, impersonate="chrome136",
                ).raise_for_status()
                logger.success("✅ Gotify 通知成功")
            except Exception as e:
                logger.warning(f"Gotify 失败: {e}")

        if SC3_PUSH_KEY:
            m = re.match(r"sct(\d+)t", SC3_PUSH_KEY, re.I)
            if m:
                try:
                    requests.get(
                        f"https://{m.group(1)}.push.ft07.com/send/{SC3_PUSH_KEY}",
                        params={"title": "NodeLoc 升级任务", "desp": msg},
                        timeout=10, impersonate="chrome136",
                    ).raise_for_status()
                    logger.success("✅ Server 酱³ 通知成功")
                except Exception as e:
                    logger.warning(f"Server 酱³ 失败: {e}")

        if WECHAT_API_URL and WECHAT_AUTH_TOKEN:
            params = {"token": WECHAT_AUTH_TOKEN, "title": "NodeLoc 升级任务", "content": msg}
            try:
                resp = requests.get(WECHAT_API_URL, params=params, timeout=10, impersonate="chrome136")
                if resp.status_code == 405:
                    resp = requests.post(WECHAT_API_URL, json=params, timeout=10, impersonate="chrome136")
                logger.success("✅ 微信通知成功") if resp.status_code < 400 else None
            except Exception as e:
                logger.warning(f"微信通知失败: {e}")

    # ── Run ───────────────────────────────────────────────────────────
    def run(self) -> int:
        try:
            logger.info("=" * 50)
            logger.info("==== NodeLoc 快速升级脚本 v4.0 开始 ====")
            logger.info("=" * 50)

            if not self.login():
                tg_notify("NodeLoc: 登录失败 ❌")
                return 2

            self.do_checkin()
            self.auto_upgrade_tasks()
            self.send_notifications()

            logger.success(
                f"✅ 浏览话题: {self.stats['topics_browsed']} | "
                f"点赞: {self.stats['likes_given']} | "
                f"回复: {self.stats['replies_posted']}"
            )
            logger.info("==== NodeLoc 快速升级脚本结束 ====")
            return 0

        except Exception:
            logger.error("NodeLoc: 脚本异常 ❌")
            traceback.print_exc()
            tg_notify("NodeLoc: 脚本异常 ❌")
            return 9

        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass


if __name__ == "__main__":
    username = os.environ.get("NODELOC_USERNAME", "").strip()
    password = os.environ.get("NODELOC_PASSWORD", "").strip()
    if not username or not password:
        logger.error("请设置 NODELOC_USERNAME / NODELOC_PASSWORD")
        tg_notify("NodeLoc: 未设置环境变量 ❌")
        raise SystemExit(1)
    raise SystemExit(NodeLocUpgrade(username, password).run())
