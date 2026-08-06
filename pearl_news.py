"""
珍珠珠宝新闻聚合器
从搜狗新闻等渠道抓取珍珠/珠宝相关新闻，通过钉钉机器人推送摘要。
支持 GitHub Actions 定时运行（每天北京时间 8:00）。
"""

import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

# ── 日志配置 ─────────────────────────────────────────────
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 搜索关键词 - 分组策略，确保覆盖面
# 第一组：核心词（高优先级）
KEYWORDS_CORE = [
    "珍珠",
    "珠宝 珍珠",
    "珍珠项链",
    "珍珠首饰",
]

# 第二组：品牌词
KEYWORDS_BRAND = [
    "御木本 珍珠",
    "Mikimoto",
    "京润珍珠",
    "周大福 珍珠",
    "TASAKI 珍珠",
    "阮仕珍珠",
]

# 第三组：事件词
KEYWORDS_EVENT = [
    "珍珠 新品发布",
    "珍珠 代言人",
    "珠宝展 珍珠",
    "珍珠 拍卖",
    "珍珠 高定",
]

# 第四组：趋势词
KEYWORDS_TREND = [
    "珍珠 时尚",
    "珍珠 穿搭",
    "珍珠 收藏",
    "淡水珍珠",
    "海水珍珠",
    "巴洛克珍珠",
]

# 请求超时（秒）
REQUEST_TIMEOUT = 15

# 钉钉消息最大长度
DINGTALK_MAX_LEN = 18000

# 过滤词（排除不相关内容）
FILTER_WORDS = ["珍珠奶茶", "奶茶店", "奶茶品牌", "游戏", "手游"]

# 排除的来源/域名（百科、医疗、电商、社交等非新闻）
EXCLUDE_DOMAINS = [
    "baike", "百科", "wiki",
    "1688.com", "taobao", "淘宝", "天猫", "jd.com",
    "杏林普康", "有来医生", "寻医问药",
    "360百科", "搜狗百科", "百度百科",
    "you.163.com", "严选",
    "gpai.net",
    "tieba.baidu", "百度贴吧",
    "douyin.com", "抖音",
    "zhihu.com", "知乎",
    "jianshu.com", "简书",
    "meipian.cn", "美篇",
    "tiffany.com", "cartier.com", "bvlgari.com",
    "chinajeweler.com/zhenzhu",
    "jingrun.com",
    "smzdm.com", "什么值得买",
]

# 珍珠珠宝相关关键词（用于二次过滤）
RELEVANT_KEYWORDS = [
    "珍珠", "珠宝", "首饰", "饰品", "项链", "手链", "戒指",
    "耳环", "胸针", "皇冠", "Mikimoto", "御木本", "京润",
    "阮仕", "天使之泪", "黛米", "周大福", "周生生", "老凤祥",
    "卡地亚", "蒂芙尼", "宝格丽", "梵克雅宝",
    "TASAKI", "塔思琦", "Pandora", "潘多拉", "高定", "高级珠宝",
    "珠宝展", "拍卖会", "代言人", "新品", "发布",
]


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
def parse_sogou_news(keyword: str) -> list[dict]:
    """解析搜狗新闻搜索结果"""
    results = []
    url = f"https://news.sogou.com/news?query={quote(keyword)}&sort=1"
    resp = safe_get(url)
    if not resp:
        return results

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
            if not title or len(title) < 4:
                continue

            # 过滤不相关内容
            if any(fw in title for fw in FILTER_WORDS):
                continue

            link = title_tag.get("href", "")
            if link and not link.startswith("http"):
                link = urljoin("https://news.sogou.com", link)

            # 获取摘要
            summary = ""
            summary_tag = item.select_one("p.txt-info") or item.select_one(".txt-info")
            if summary_tag:
                summary = summary_tag.get_text(strip=True)[:200]

            # 获取来源
            source = "搜狗新闻"
            source_tag = item.select_one(".news-from") or item.select_one(".from")
            if source_tag:
                source = source_tag.get_text(strip=True)

            results.append({
                "title": title,
                "url": link,
                "summary": summary,
                "source": source,
            })
        except Exception as e:
            logger.debug(f"解析搜狗新闻条目失败: {e}")

    return results


def parse_baidu_news(keyword: str) -> list[dict]:
    """解析百度资讯搜索结果（备用，可能被反爬）"""
    results = []
    url = f"https://www.baidu.com/s?tn=news&wd={quote(keyword)}"
    resp = safe_get(url)
    if not resp:
        return results

    # 检查是否被反爬
    if "安全验证" in resp.text or len(resp.text) < 1000:
        logger.debug("百度资讯触发反爬验证，跳过")
        return results

    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    containers = soup.select(".c-container")
    for container in containers:
        try:
            h3 = container.select_one("h3 a")
            if not h3:
                continue

            title = h3.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            if any(fw in title for fw in FILTER_WORDS):
                continue

            link = h3.get("href", "")

            source = ""
            src_tag = (
                container.select_one(".c-color-gray")
                or container.select_one(".c-author")
            )
            if src_tag:
                source = src_tag.get_text(strip=True)

            results.append({
                "title": title,
                "url": link,
                "summary": "",
                "source": f"百度资讯 - {source}" if source else "百度资讯",
            })
        except Exception as e:
            logger.debug(f"解析百度资讯条目失败: {e}")

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
    """过滤出与珍珠/珠宝强相关的新闻，排除百科、医疗、电商等"""
    filtered = []
    for item in items:
        title = item.get("title", "")
        source = item.get("source", "")
        url = item.get("url", "")

        # 检查是否包含相关关键词
        if not any(kw in title for kw in RELEVANT_KEYWORDS):
            continue

        # 排除非新闻来源
        combined_text = f"{title} {source} {url}".lower()
        if any(ex in combined_text for ex in EXCLUDE_DOMAINS):
            continue

        filtered.append(item)
    return filtered


# ── 钉钉推送 ──────────────────────────────────────────────
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
        lines.append(f"### 📌 {source}\n")
        for i, item in enumerate(source_items[:10], 1):
            title_text = item["title"]
            url = item.get("url", "")

            if url:
                lines.append(f"{i}. [{title_text}]({url})")
            else:
                lines.append(f"{i}. {title_text}")

            if item.get("summary"):
                lines.append(f"   > {item['summary'][:120]}\n")
            else:
                lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("*由珍珠珠宝新闻机器人自动生成 · 数据来源: 搜狗新闻 / 百度资讯*")

    content = "\n".join(lines)

    # 截断过长内容
    if len(content) > DINGTALK_MAX_LEN:
        content = content[:DINGTALK_MAX_LEN] + "\n\n...(内容过长已截断)"

    return title, content


# ── 主流程 ────────────────────────────────────────────────
def collect_news() -> list[dict]:
    """从所有数据源收集新闻"""
    all_items = []

    # 1. 搜狗新闻（主力数据源）
    logger.info("=== 开始抓取搜狗新闻 ===")
    all_keywords = KEYWORDS_CORE + KEYWORDS_BRAND + KEYWORDS_EVENT + KEYWORDS_TREND
    for kw in all_keywords:
        logger.info(f"  搜索: {kw}")
        items = parse_sogou_news(kw)
        logger.info(f"  获取 {len(items)} 条")
        all_items.extend(items)
        time.sleep(1.5)  # 礼貌间隔

    # 2. 百度资讯（备用数据源）
    logger.info("=== 开始抓取百度资讯 ===")
    for kw in KEYWORDS_CORE + KEYWORDS_EVENT:
        logger.info(f"  搜索: {kw}")
        items = parse_baidu_news(kw)
        logger.info(f"  获取 {len(items)} 条")
        all_items.extend(items)
        time.sleep(1.5)

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
