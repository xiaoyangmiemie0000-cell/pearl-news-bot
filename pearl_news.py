"""
珍珠珠宝新闻聚合器
从搜狗新闻等渠道抓取珍珠/珠宝相关新闻，通过 LLM 智能摘要后，
按「时间 / 地点 / 人物 / 事件 / 影响」格式归纳，通过钉钉机器人推送。
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

# ── 常量 ─────────────────────────────────────────────────
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
KEYWORDS_CORE = [
    "珍珠",
    "珠宝 珍珠",
    "珍珠项链",
    "珍珠首饰",
]

KEYWORDS_BRAND = [
    "御木本 珍珠",
    "Mikimoto",
    "京润珍珠",
    "周大福 珍珠",
    "TASAKI 珍珠",
    "阮仕珍珠",
]

KEYWORDS_EVENT = [
    "珍珠 新品发布",
    "珍珠 代言人",
    "珠宝展 珍珠",
    "珍珠 拍卖",
    "珍珠 高定",
]

KEYWORDS_TREND = [
    "珍珠 时尚",
    "珍珠 穿搭",
    "珍珠 收藏",
    "淡水珍珠",
    "海水珍珠",
    "巴洛克珍珠",
]

REQUEST_TIMEOUT = 15
DINGTALK_MAX_LEN = 18000

FILTER_WORDS = ["珍珠奶茶", "奶茶店", "奶茶品牌", "游戏", "手游"]

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

RELEVANT_KEYWORDS = [
    "珍珠", "珠宝", "首饰", "饰品", "项链", "手链", "戒指",
    "耳环", "胸针", "皇冠", "Mikimoto", "御木本", "京润",
    "阮仕", "天使之泪", "黛米", "周大福", "周生生", "老凤祥",
    "卡地亚", "蒂芙尼", "宝格丽", "梵克雅宝",
    "TASAKI", "塔思琦", "Pandora", "潘多拉", "高定", "高级珠宝",
    "珠宝展", "拍卖会", "代言人", "新品", "发布",
]

# ── LLM 配置 ─────────────────────────────────────────────
# 支持 OpenAI 兼容接口（DeepSeek / 通义千问 / 智谱 / OpenAI 等）
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://api.deepseek.com")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# LLM 摘要提示词
SUMMARY_PROMPT = """\
你是一位专业的珠宝行业新闻分析师。请根据以下新闻标题和摘要内容，
按照以下格式进行结构化归纳总结。如果某项信息在原文中未提及，请标注"未明确提及"。

请严格按以下格式输出（不要输出其他内容）：

📅 时间：[新闻发生的时间]
📍 地点：[事件发生的地点]
👤 人物/机构：[涉及的关键人物、品牌或机构]
 事件：[用1-2句话概括核心事件]
💡 影响：[分析该事件对珍珠/珠宝行业的影响或意义]
🔗 来源：[保留原始链接]

---

新闻标题：{title}
新闻摘要：{summary}
新闻来源：{source}
"""


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

    items = soup.select(".news-list li") or soup.select(".vrwrap") or soup.select(".result")

    for item in items:
        try:
            title_tag = item.select_one("h3 a") or item.select_one("a")
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            if any(fw in title for fw in FILTER_WORDS):
                continue

            link = title_tag.get("href", "")
            if link and not link.startswith("http"):
                link = urljoin("https://news.sogou.com", link)

            summary = ""
            summary_tag = item.select_one("p.txt-info") or item.select_one(".txt-info")
            if summary_tag:
                summary = summary_tag.get_text(strip=True)[:200]

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
    """解析百度资讯搜索结果（备用）"""
    results = []
    url = f"https://www.baidu.com/s?tn=news&wd={quote(keyword)}"
    resp = safe_get(url)
    if not resp:
        return results

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


def fetch_article_content(url: str) -> str:
    """尝试抓取新闻正文内容，用于 LLM 摘要"""
    resp = safe_get(url, timeout=10)
    if not resp:
        return ""

    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # 移除 script/style
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # 尝试常见的正文容器
    article = (
        soup.select_one("article")
        or soup.select_one(".article-content")
        or soup.select_one(".news-content")
        or soup.select_one(".content")
        or soup.select_one("#content")
        or soup.select_one(".text")
    )

    if article:
        text = article.get_text(separator="\n", strip=True)
    else:
        # 退而求其次，取所有段落
        paragraphs = soup.find_all("p")
        text = "\n".join(p.get_text(strip=True) for p in paragraphs)

    # 清理多余空白
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    # 只取前 2000 字符，避免 LLM 输入过长
    return text[:2000] if text else ""


# ── LLM 智能摘要 ─────────────────────────────────────────
def llm_summarize(item: dict) -> str:
    """调用 LLM 对单条新闻进行结构化摘要"""
    if not LLM_API_KEY:
        return ""

    title = item.get("title", "")
    summary = item.get("summary", "")
    source = item.get("source", "")
    url = item.get("url", "")

    # 如果有正文内容，优先使用正文
    content = item.get("content", "")
    if not content and url:
        content = fetch_article_content(url)

    prompt = SUMMARY_PROMPT.format(
        title=title,
        summary=summary if summary else content[:500] if content else "无摘要",
        source=source,
    )

    try:
        resp = requests.post(
            f"{LLM_API_BASE}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 500,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"LLM 摘要失败: {e}")
        return ""


def batch_summarize(items: list[dict], max_items: int = 15) -> list[dict]:
    """批量对新闻进行 LLM 智能摘要，返回带 summary_llm 字段的结果"""
    if not LLM_API_KEY:
        logger.warning("未配置 LLM_API_KEY，跳过智能摘要")
        for item in items:
            item["summary_llm"] = ""
        return items

    # 限制数量，避免 API 调用过多
    items_to_summarize = items[:max_items]
    logger.info(f"开始对 {len(items_to_summarize)} 条新闻进行 LLM 智能摘要...")

    for i, item in enumerate(items_to_summarize, 1):
        logger.info(f"  [{i}/{len(items_to_summarize)}] 摘要: {item['title'][:40]}...")
        summary = llm_summarize(item)
        item["summary_llm"] = summary
        # 每次调用间隔，避免触发限流
        time.sleep(1)

    # 未处理的项目标记为空
    for item in items[max_items:]:
        item["summary_llm"] = ""

    return items


# ─ 新闻去重与过滤 ────────────────────────────────────────
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
    filtered = []
    for item in items:
        title = item.get("title", "")
        source = item.get("source", "")
        url = item.get("url", "")

        if not any(kw in title for kw in RELEVANT_KEYWORDS):
            continue

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
    """构建钉钉 Markdown 消息（含 LLM 智能摘要）"""
    title = f"💎 珍珠珠宝日报 - {date_str}"

    lines = [
        f"## 💎 珍珠珠宝日报",
        f"**{date_str}**",
        f"共收集 **{len(items)}** 条资讯，以下为智能摘要精选\n",
        "---\n",
    ]

    for i, item in enumerate(items, 1):
        summary_llm = item.get("summary_llm", "")
        raw_title = item.get("title", "")
        url = item.get("url", "")

        if summary_llm:
            # 使用 LLM 智能摘要
            lines.append(f"###  第{i}条\n")
            lines.append(summary_llm)
            lines.append("")
        else:
            # 降级：使用原始标题 + 链接
            if url:
                lines.append(f"### {i}. [{raw_title}]({url})\n")
            else:
                lines.append(f"### {i}. {raw_title}\n")

            if item.get("summary"):
                lines.append(f"> {item['summary'][:150]}\n")
            lines.append("")

    lines.append("---")
    has_llm = any(item.get("summary_llm") for item in items)
    if has_llm:
        lines.append("*由 AI 智能摘要生成 · 数据来源: 搜狗新闻 / 百度资讯*")
    else:
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
        time.sleep(1.5)

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

    if relevant_items:
        return relevant_items
    return unique_items


def main():
    """主入口"""
    webhook_url = os.environ.get("DINGTALK_WEBHOOK")

    # 收集新闻
    items = collect_news()

    if not items:
        logger.warning("未收集到任何新闻")
        if not webhook_url:
            print("\n未收集到任何新闻，请检查网络连接或关键词设置。")
        return

    # LLM 智能摘要
    items = batch_summarize(items, max_items=15)

    # 构建消息
    date_str = datetime.now().strftime("%Y-%m-%d")
    title, content = build_message(items, date_str)

    if webhook_url:
        send_dingtalk(webhook_url, title, content)
    else:
        print("\n" + "=" * 60)
        print(title)
        print("=" * 60)
        print(content)


if __name__ == "__main__":
    main()
