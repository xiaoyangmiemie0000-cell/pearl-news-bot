"""
珍珠珠宝新闻聚合器
从 Google News RSS、搜狗新闻等渠道抓取珍珠/珠宝相关新闻，通过钉钉机器人推送摘要。
"""

import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin, parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

# ── 日志配置 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 搜索关键词（覆盖新品、代言人、品牌、趋势等维度）
KEYWORDS = [
    "珍珠 珠宝 新品",
    "珍珠 代言人 品牌",
    "珍珠首饰 发布",
    "珠宝 珍珠 新款",
    "珍珠 拍卖 收藏",
    "淡水珍珠 海水珍珠",
    "珍珠项链 明星 同款",
    "珠宝展 珍珠 展览",
    "珍珠 时尚 趋势 2026",
    "珍珠 品牌 营销",
]

# 请求超时（秒）
REQUEST_TIMEOUT = 20

# 钉钉消息最大长度
DINGTALK_MAX_LEN = 18000

# 过滤词（排除不相关内容）
FILTER_WORDS = ["珍珠奶茶", "奶茶", "游戏", "手游", "王者荣耀", "股票", "基金", "彩票"]


# ── 网络请求工具 ──────────────────────────────────────────
def safe_get(url: str, timeout: int = REQUEST_TIMEOUT) -> requests.Response | None:
    """带重试的 GET 请求"""
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            return resp
        except Exception as e:
            logger.warning(f"请求失败 (第{attempt+1}次): {url} -> {e}")
            time.sleep(2)
    return None


# ── 解析器 ────────────────────────────────────────────────
def parse_google_news_rss(keyword: str) -> list[dict]:
    """通过 Google News RSS 搜索新闻"""
    results = []
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote(keyword)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )
    resp = safe_get(url)
    if not resp:
        return results

    soup = BeautifulSoup(resp.text, "xml")
    items = soup.find_all("item")

    for item in items:
        try:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            source = item.find("source")

            if not title:
                continue

            title_text = title.text.strip()
            # 过滤不相关内容
            if any(fw in title_text for fw in FILTER_WORDS):
                continue

            link_text = link.text.strip() if link else ""
            date_text = pub_date.text.strip() if pub_date else ""
            source_text = source.text.strip() if source else "Google News"

            # 尝试获取真实链接（Google News 会重定向）
            real_url = resolve_google_news_url(link_text)

            results.append({
                "title": title_text,
                "url": real_url or link_text,
                "summary": "",
                "source": source_text,
                "date": date_text,
            })
        except Exception as e:
            logger.debug(f"解析 Google News RSS 条目失败: {e}")

    return results


def resolve_google_news_url(google_url: str) -> str:
    """尝试从 Google News 重定向 URL 中提取真实 URL"""
    if not google_url:
        return ""
    try:
        parsed = urlparse(google_url)
        if "news.google.com" in parsed.netloc:
            # Google News RSS 链接通常包含 oc 参数
            # 尝试直接访问获取重定向
            resp = requests.head(google_url, headers=HEADERS, timeout=5, allow_redirects=True)
            return resp.url
    except Exception:
        pass
    return google_url


def parse_sogou_news(keyword: str) -> list[dict]:
    """解析搜狗新闻搜索结果"""
    results = []
    url = f"https://news.sogou.com/news?query={quote(keyword)}&sort=1"
    resp = safe_get(url)
    if not resp:
        return results

    # 搜狗返回的编码需要特殊处理
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # 尝试多种选择器
    items = soup.select(".news-list li") or soup.select(".vrwrap") or soup.select(".result")

    for item in items:
        try:
            title_tag = item.select_one("h3 a") or item.select_one("a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if any(fw in title for fw in FILTER_WORDS):
                continue

            link = title_tag.get("href", "")
            if link and not link.startswith("http"):
                link = urljoin("https://news.sogou.com", link)

            summary = ""
            summary_tag = item.select_one("p.txt-info") or item.select_one(".txt-info")
            if summary_tag:
                summary = summary_tag.get_text(strip=True)[:200]

            results.append({
                "title": title,
                "url": link,
                "summary": summary,
                "source": "搜狗新闻",
                "date": "",
            })
        except Exception as e:
            logger.debug(f"解析搜狗新闻条目失败: {e}")

    return results


# ── 新闻去重与过滤 ────────────────────────────────────────
def deduplicate(items: list[dict]) -> list[dict]:
    """基于标题去重"""
    seen_hashes = set()
    unique = []
    for item in items:
        h = hashlib.md5(item["title"].encode()).hexdigest()
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique.append(item)
    return unique


def filter_relevant(items: list[dict]) -> list[dict]:
    """过滤出与珍珠/珠宝强相关的新闻"""
    relevant_keywords = [
        "珍珠", "珠宝", "首饰", "饰品", "项链", "手链", "戒指",
        "耳环", "胸针", "皇冠", "Mikimoto", "御木本", "京润",
        "阮仕", "天使之泪", "黛米", "周大福", "周生生", "老凤祥",
        "卡地亚", "蒂芙尼", "宝格丽", "梵克雅宝", "海瑞温斯顿",
        "拍卖", "珠宝展", "代言人", "新品", "发布", "高定",
    ]
    filtered = []
    for item in items:
        title = item.get("title", "")
        if any(kw in title for kw in relevant_keywords):
            filtered.append(item)
    return filtered


# ── 钉钉推送 ─────────────────────────────────────────────
def send_dingtalk(webhook_url: str, title: str, content: str) -> bool:
    """通过钉钉机器人 Webhook 发送 Markdown 消息"""
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": content,
        },
    }
    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info("钉钉消息发送成功")
            return True
        else:
            logger.error(f"钉钉消息发送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"钉钉消息发送异常: {e}")
        return False


def build_message(items: list[dict], date_str: str) -> tuple[str, str]:
    """构建钉钉 Markdown 消息"""
    title = f"💎 珍珠珠宝日报 - {date_str}"

    lines = [f"## 💎 珍珠珠宝日报\n", f"**{date_str}**\n"]
    lines.append(f"共收集到 **{len(items)}** 条相关资讯\n")
    lines.append("---\n")

    # 按来源分组
    by_source: dict[str, list[dict]] = {}
    for item in items:
        src = item.get("source", "其他")
        by_source.setdefault(src, []).append(item)

    for source, source_items in by_source.items():
        lines.append(f"###  {source}\n")
        for i, item in enumerate(source_items[:8], 1):
            title_text = item["title"]
            url = item.get("url", "")
            date_info = item.get("date", "")

            if url:
                lines.append(f"{i}. [{title_text}]({url})")
            else:
                lines.append(f"{i}. {title_text}")

            meta_parts = []
            if date_info:
                # 简化日期显示
                try:
                    dt = datetime.strptime(date_info, "%a, %d %b %Y %H:%M:%S %Z")
                    meta_parts.append(dt.strftime("%m-%d %H:%M"))
                except Exception:
                    meta_parts.append(date_info[:16])
            if meta_parts:
                lines.append(f"   > 📅 {' | '.join(meta_parts)}\n")
            else:
                lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("*由珍珠珠宝新闻机器人自动生成 · 数据来源: Google News / 搜狗新闻*")

    content = "\n".join(lines)

    # 截断过长内容
    if len(content) > DINGTALK_MAX_LEN:
        content = content[:DINGTALK_MAX_LEN] + "\n\n...(内容过长已截断)"

    return title, content


# ── 主流程 ────────────────────────────────────────────────
def collect_news() -> list[dict]:
    """从所有数据源收集新闻"""
    all_items = []

    # 1. Google News RSS（主力数据源，每个关键词取前10条）
    logger.info("=== 开始抓取 Google News RSS ===")
    for kw in KEYWORDS:
        logger.info(f"  搜索: {kw}")
        items = parse_google_news_rss(kw)
        logger.info(f"  获取 {len(items)} 条")
        all_items.extend(items)
        time.sleep(1)  # 礼貌间隔

    # 2. 搜狗新闻（补充数据源）
    logger.info("=== 开始抓取搜狗新闻 ===")
    for kw in KEYWORDS[:5]:  # 限制关键词数量
        logger.info(f"  搜索: {kw}")
        items = parse_sogou_news(kw)
        logger.info(f"  获取 {len(items)} 条")
        all_items.extend(items)
        time.sleep(1)

    # 去重
    unique_items = deduplicate(all_items)
    logger.info(f"总计收集 {len(all_items)} 条，去重后 {len(unique_items)} 条")

    # 过滤出珍珠/珠宝相关内容
    relevant_items = filter_relevant(unique_items)
    logger.info(f"过滤后保留 {len(relevant_items)} 条相关新闻")

    # 如果没有过滤到相关内容，就返回去重后的全部结果
    if relevant_items:
        return relevant_items
    return unique_items


def main():
    """主入口"""
    # 获取钉钉 Webhook
    webhook_url = os.environ.get("DINGTALK_WEBHOOK")

    # 收集新闻
    items = collect_news()

    if not items:
        logger.warning("未收集到任何新闻")
        if not webhook_url:
            print("\n未收集到任何新闻，请检查网络连接或关键词设置。")
        return

    # 构建消息
    date_str = datetime.now().strftime("%Y-%m-%d")
    title, content = build_message(items, date_str)

    if webhook_url:
        # 生产模式：发送钉钉
        send_dingtalk(webhook_url, title, content)
    else:
        # 测试模式：输出到控制台
        print("\n" + "=" * 60)
        print(title)
        print("=" * 60)
        print(content)


if __name__ == "__main__":
    main()
