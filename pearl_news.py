"""
珍珠珠宝新闻聚合器
从多个渠道抓取珍珠/珠宝相关新闻，通过钉钉机器人推送摘要。
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

# 搜索关键词
KEYWORDS = [
    "珍珠 新品",
    "珍珠 代言人",
    "珍珠首饰 发布",
    "珠宝 珍珠 新款",
    "珍珠 品牌 发布",
    "淡水珍珠 新品",
    "海水珍珠 拍卖",
    "珍珠项链 明星",
    "珠宝展 珍珠",
    "珍珠 时尚 趋势",
]

# 请求超时（秒）
REQUEST_TIMEOUT = 15

# 钉钉消息最大长度
DINGTALK_MAX_LEN = 18000


# ── 数据源定义 ────────────────────────────────────────────
# 综合新闻
SOURCES_NEWS = [
    {
        "name": "百度新闻",
        "url_tpl": "https://www.baidu.com/s?wd={kw}&tn=news&rn=10",
        "parser": "baidu_news",
    },
    {
        "name": "搜狗新闻",
        "url_tpl": "https://news.sogou.com/news?query={kw}&sort=1",
        "parser": "sogou_news",
    },
]

# 珠宝行业网站
SOURCES_INDUSTRY = [
    {
        "name": "中国珠宝网",
        "url": "https://www.zhubao.cn",
        "parser": "zhubao_cn",
    },
]

# 社交媒体
SOURCES_SOCIAL = [
    {
        "name": "微博搜索",
        "url_tpl": "https://s.weibo.com/weibo?q={kw}&timescope=custom:today",
        "parser": "weibo",
    },
]

# 电商平台
SOURCES_ECOM = [
    {
        "name": "京东搜索",
        "url_tpl": "https://search.jd.com/Search?keyword={kw}&enc=utf-8",
        "parser": "jd",
    },
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
            time.sleep(1)
    return None


def detect_encoding(resp: requests.Response) -> str:
    """检测网页编码"""
    if resp.encoding and resp.encoding.lower() != "iso-8859-1":
        return resp.encoding
    # 从内容推断
    content_lower = resp.content[:2000].decode("ascii", errors="ignore").lower()
    if "gbk" in content_lower or "gb2312" in content_lower:
        return "gbk"
    return "utf-8"


# ── 解析器 ────────────────────────────────────────────────
def parse_baidu_news(resp: requests.Response) -> list[dict]:
    """解析百度新闻搜索结果"""
    results = []
    resp.encoding = detect_encoding(resp)
    soup = BeautifulSoup(resp.text, "html.parser")

    for item in soup.select(".result"):
        try:
            title_tag = item.select_one("h3 a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            link = title_tag.get("href", "")

            summary = ""
            summary_tag = item.select_one(".c-summary") or item.select_one(".c-abstract")
            if summary_tag:
                summary = summary_tag.get_text(strip=True)[:200]

            source = ""
            source_tag = item.select_one(".c-author span") or item.select_one(".c-color-gray")
            if source_tag:
                source = source_tag.get_text(strip=True)

            if title and link:
                results.append({
                    "title": title,
                    "url": link,
                    "summary": summary,
                    "source": f"百度新闻 - {source}" if source else "百度新闻",
                })
        except Exception as e:
            logger.debug(f"解析百度新闻条目失败: {e}")

    return results


def parse_sogou_news(resp: requests.Response) -> list[dict]:
    """解析搜狗新闻搜索结果"""
    results = []
    resp.encoding = detect_encoding(resp)
    soup = BeautifulSoup(resp.text, "html.parser")

    for item in soup.select(".news-list li") or soup.select(".vrwrap"):
        try:
            title_tag = item.select_one("h3 a") or item.select_one("a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            link = title_tag.get("href", "")
            if link and not link.startswith("http"):
                link = urljoin("https://news.sogou.com", link)

            summary = ""
            summary_tag = item.select_one("p.txt-info") or item.select_one(".txt-info")
            if summary_tag:
                summary = summary_tag.get_text(strip=True)[:200]

            if title:
                results.append({
                    "title": title,
                    "url": link,
                    "summary": summary,
                    "source": "搜狗新闻",
                })
        except Exception as e:
            logger.debug(f"解析搜狗新闻条目失败: {e}")

    return results


def parse_zhubao_cn(resp: requests.Response) -> list[dict]:
    """解析中国珠宝网首页新闻"""
    results = []
    resp.encoding = detect_encoding(resp)
    soup = BeautifulSoup(resp.text, "html.parser")

    for a_tag in soup.select("a[href]"):
        try:
            title = a_tag.get_text(strip=True)
            if len(title) < 6 or len(title) > 80:
                continue
            # 过滤包含珍珠/珠宝关键词的链接
            if not any(kw in title for kw in ["珍珠", "珠宝", "首饰", "饰品", "新品", "发布"]):
                continue
            link = a_tag.get("href", "")
            if link and not link.startswith("http"):
                link = urljoin("https://www.zhubao.cn", link)
            results.append({
                "title": title,
                "url": link,
                "summary": "",
                "source": "中国珠宝网",
            })
        except Exception as e:
            logger.debug(f"解析中国珠宝网条目失败: {e}")

    # 去重
    seen = set()
    unique = []
    for r in results:
        if r["title"] not in seen:
            seen.add(r["title"])
            unique.append(r)
    return unique[:15]


def parse_weibo(resp: requests.Response) -> list[dict]:
    """解析微博搜索结果"""
    results = []
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select(".card-wrap"):
        try:
            content_tag = card.select_one("p.txt") or card.select_one(".txt")
            if not content_tag:
                continue
            text = content_tag.get_text(strip=True)[:200]
            if len(text) < 10:
                continue

            action_tag = card.select_one("a[action-type='feed_list_detail']")
            link = ""
            if action_tag:
                href = action_tag.get("href", "")
                link = urljoin("https://s.weibo.com", href) if href else ""

            results.append({
                "title": text[:60] + ("..." if len(text) > 60 else ""),
                "url": link,
                "summary": text,
                "source": "微博",
            })
        except Exception as e:
            logger.debug(f"解析微博条目失败: {e}")

    return results


def parse_jd(resp: requests.Response) -> list[dict]:
    """解析京东搜索结果（新品信息）"""
    results = []
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    for item in soup.select(".gl-item") or soup.select("li.gl-i"):
        try:
            title_tag = item.select_one(".p-name a em") or item.select_one(".p-name a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if len(title) < 5:
                continue

            link_tag = item.select_one(".p-name a")
            link = link_tag.get("href", "") if link_tag else ""
            if link and not link.startswith("http"):
                link = "https:" + link

            price_tag = item.select_one(".p-price strong i")
            price = f"¥{price_tag.get_text(strip=True)}" if price_tag else ""

            summary = f"价格: {price}" if price else ""

            results.append({
                "title": title[:60],
                "url": link,
                "summary": summary,
                "source": "京东",
            })
        except Exception as e:
            logger.debug(f"解析京东条目失败: {e}")

    return results[:10]


# 解析器注册表
PARSERS = {
    "baidu_news": parse_baidu_news,
    "sogou_news": parse_sogou_news,
    "zhubao_cn": parse_zhubao_cn,
    "weibo": parse_weibo,
    "jd": parse_jd,
}


# ── 新闻去重与排序 ────────────────────────────────────────
def deduplicate(items: list[dict]) -> list[dict]:
    """基于标题相似度去重"""
    seen_hashes = set()
    unique = []
    for item in items:
        # 用标题的哈希做简单去重
        h = hashlib.md5(item["title"].encode()).hexdigest()
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique.append(item)
    return unique


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
        for i, item in enumerate(source_items[:5], 1):
            title_text = item["title"]
            url = item.get("url", "")
            if url:
                lines.append(f"{i}. [{title_text}]({url})")
            else:
                lines.append(f"{i}. {title_text}")
            if item.get("summary"):
                lines.append(f"   > {item['summary'][:100]}\n")
            else:
                lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("*由珍珠珠宝新闻机器人自动生成*")

    content = "\n".join(lines)

    # 截断过长内容
    if len(content) > DINGTALK_MAX_LEN:
        content = content[:DINGTALK_MAX_LEN] + "\n\n...(内容过长已截断)"

    return title, content


# ── 主流程 ────────────────────────────────────────────────
def collect_news() -> list[dict]:
    """从所有数据源收集新闻"""
    all_items = []

    # 1. 综合新闻（按关键词搜索）
    for source in SOURCES_NEWS:
        parser_fn = PARSERS.get(source["parser"])
        if not parser_fn:
            continue
        for kw in KEYWORDS[:5]:  # 限制关键词数量避免请求过多
            url = source["url_tpl"].format(kw=quote(kw))
            logger.info(f"抓取: {source['name']} - {kw}")
            resp = safe_get(url)
            if resp:
                items = parser_fn(resp)
                logger.info(f"  获取 {len(items)} 条")
                all_items.extend(items)
            time.sleep(1)  # 礼貌间隔

    # 2. 珠宝行业网站
    for source in SOURCES_INDUSTRY:
        parser_fn = PARSERS.get(source["parser"])
        if not parser_fn:
            continue
        logger.info(f"抓取: {source['name']}")
        resp = safe_get(source["url"])
        if resp:
            items = parser_fn(resp)
            logger.info(f"  获取 {len(items)} 条")
            all_items.extend(items)
        time.sleep(1)

    # 3. 社交媒体
    for source in SOURCES_SOCIAL:
        parser_fn = PARSERS.get(source["parser"])
        if not parser_fn:
            continue
        for kw in KEYWORDS[:3]:
            url = source["url_tpl"].format(kw=quote(kw))
            logger.info(f"抓取: {source['name']} - {kw}")
            resp = safe_get(url)
            if resp:
                items = parser_fn(resp)
                logger.info(f"  获取 {len(items)} 条")
                all_items.extend(items)
            time.sleep(2)

    # 4. 电商平台
    for source in SOURCES_ECOM:
        parser_fn = PARSERS.get(source["parser"])
        if not parser_fn:
            continue
        for kw in KEYWORDS[:3]:
            url = source["url_tpl"].format(kw=quote(kw))
            logger.info(f"抓取: {source['name']} - {kw}")
            resp = safe_get(url)
            if resp:
                items = parser_fn(resp)
                logger.info(f"  获取 {len(items)} 条")
                all_items.extend(items)
            time.sleep(2)

    # 去重
    unique_items = deduplicate(all_items)
    logger.info(f"总计收集 {len(all_items)} 条，去重后 {len(unique_items)} 条")
    return unique_items


def main():
    """主入口"""
    # 获取钉钉 Webhook
    webhook_url = os.environ.get("DINGTALK_WEBHOOK")
    if not webhook_url:
        logger.error("未设置 DINGTALK_WEBHOOK 环境变量！")
        logger.info("请在 GitHub Settings > Secrets 中设置 DINGTALK_WEBHOOK")
        # 本地测试时输出到控制台
        items = collect_news()
        date_str = datetime.now().strftime("%Y-%m-%d")
        title, content = build_message(items, date_str)
        print("\n" + "=" * 60)
        print(title)
        print("=" * 60)
        print(content)
        return

    # 收集新闻
    items = collect_news()

    if not items:
        logger.warning("未收集到任何新闻，跳过推送")
        return

    # 构建消息
    date_str = datetime.now().strftime("%Y-%m-%d")
    title, content = build_message(items, date_str)

    # 发送钉钉
    send_dingtalk(webhook_url, title, content)


if __name__ == "__main__":
    main()
