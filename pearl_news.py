"""
珍珠饰品新闻日报聚合器 v3
从 Bing News、中宝协官网、今日热榜(微博热搜)等多渠道抓取珍珠饰品/珠宝相关新闻，
按主题分类整理成日报，通过钉钉机器人推送。

核心特性：
- 多源聚合：中宝协(权威行业) + Bing News(综合) + 今日热榜(社交热点) + 搜狗(备用)
- 精准品类：8 层过滤确保仅保留珍珠饰品行业内容
  - 排除药品(珍珠药膏)、化妆品(珍珠面膜)、食材(珍珠奶茶)、日用品等非饰品内容
  - 检测比喻用法(记忆里的珍珠、珍珠般的智慧)
  - 必须同时含"珍珠"字样 + 饰品行业上下文(品类词/场景词/材质词/品牌)
- 真实链接：跟随重定向 + HEAD 校验，过滤失效链接
- 严格时效：默认仅保留 48h 内热点，无热点时降级到 7d 内精选 2-4 条
- 主题分类：政策/市场/明星KOL/展会/品牌/产业上游，带 emoji 标注
- 稳定推送：钉钉重试 + 全流程异常捕获，失败发告警，避免静默

支持 GitHub Actions 定时运行（北京时间 07:00 / 08:00 双触发兜底）。
"""

import os
import re
import time
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# 可选时区库：GitHub Actions 默认 UTC，需转北京时间；本地无 pytz 时用 UTC+8 偏移
try:
    from pytz import timezone as _tz
    BJT = _tz("Asia/Shanghai")
except Exception:  # pragma: no cover
    BJT = None

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

REQUEST_TIMEOUT = 15
DINGTALK_MAX_LEN = 18000

# 时效窗口
HOT_WINDOW_HOURS = 48          # 热点模式：仅保留 48h 内
FALLBACK_WINDOW_HOURS = 24 * 7  # 降级模式：放宽到 7d
HOT_MIN_COUNT = 3              # 热点条数 >=3 才走正常模式
NORMAL_MAX_COUNT = 8           # 正常模式最多推送条数
FALLBACK_MAX_COUNT = 4         # 降级模式最多推送条数

# 搜索关键词 - 分组策略（全部聚焦"珍珠"品类，可与其他品类组合）
KEYWORDS_CORE = [
    "珍珠", "珍珠项链", "珍珠首饰", "珍珠手链", "珍珠耳环",
    "珍珠戒指", "珍珠胸针", "珍珠吊坠", "珍珠手镯",
]
KEYWORDS_INDUSTRY = [
    # 珍珠与其他品类的组合（必须含珍珠）
    "珍珠 黄金", "珍珠 钻石", "珍珠 翡翠", "珍珠 宝石",
    "珍珠 K金", "珍珠 铂金", "珍珠 彩宝", "珍珠 祖母绿",
    # 珍珠产业/工艺
    "培育珍珠", "淡水珍珠", "海水珍珠", "Akoya珍珠", "巴洛克珍珠",
    "珍珠 养殖", "珍珠 产区", "珍珠 产量", "珍珠 进出口",
    # 珍珠市场/趋势
    "珍珠 价格", "珍珠 市场", "珍珠 消费", "珍珠 趋势",
    "珍珠 新品发布", "珍珠 高定", "珍珠 时尚", "珍珠 拍卖",
]
KEYWORDS_EVENT = [
    "珍珠 展会", "珍珠 博览会", "珍珠 大会", "珍珠 论坛",
    "珍珠 代言人", "珍珠 联名", "珠宝展 珍珠",
    "苏富比 珍珠", "佳士得 珍珠", "保利 珍珠",
]
KEYWORDS_CELEBRITY = [
    "明星 珍珠", "红毯 珍珠", "珍珠 明星", "珍珠 KOL",
    "珍珠 同款", "珍珠 带货", "珍珠 佩戴",
]

# 过滤词（仅保留明确无关的噪声词，避免误杀品牌新品/电商内容）
FILTER_WORDS = [
    "珍珠奶茶", "奶茶店", "奶茶品牌",
    "梦幻西游", "比特币", "BTC", "挖矿", "区块链", "加密货币",
    "乐高 航海王", "乐高 积木",
]

# 排除的来源/域名（百科、医疗、电商等非新闻）
EXCLUDE_DOMAINS = [
    "baike", "百科", "wiki",
    "1688.com", "taobao", "淘宝", "天猫", "京东", "jd.com",
    "杏林普康", "有来医生", "寻医问药",
    "360百科", "搜狗百科", "百度百科",
    "you.163.com", "严选",
    "gpai.net",
]

# 珍珠品类核心词：标题或摘要含任一词即视为"含珍珠"
# 注意：这是必要不充分条件——还必须满足 JEWELRY_CONTEXT_WORDS（饰品上下文）
# 或 FAMOUS_BRANDS/FAMOUS_PEOPLE（品牌/名人信号）才能通过
# 仅"珍珠"字样但无饰品上下文（如药品/食材/比喻）会被后续 Layer 3/6/7 过滤
PEARL_CORE_WORDS = [
    # 珍珠本词
    "珍珠", "真珠",
    # 珍珠品类细分
    "淡水珍珠", "海水珍珠", "Akoya", "巴洛克珍珠", "南洋珍珠",
    "黑珍珠", "金珍珠", "澳白珍珠", "爱迪生珍珠",
    "培育珍珠", "人工珍珠", "贝珠", "塑料珍珠",
    # 珍珠首饰
    "珍珠项链", "珍珠手链", "珍珠耳环", "珍珠戒指", "珍珠胸针",
    "珍珠吊坠", "珍珠手镯", "珍珠头饰", "珍珠脚链",
    # 珍珠+其他品类组合
    "珍珠黄金", "珍珠钻石", "珍珠翡翠", "珍珠宝石", "珍珠彩宝",
    "珍珠铂金", "珍珠K金", "珍珠祖母绿",
]

# 标题饰品品类词：标题含这些词时，即使"珍珠"只在摘要中也可通过
# 仅限具体饰品品类，避免"佩戴""时尚"等泛化词导致误判
TITLE_JEWELRY_WORDS = [
    "项链", "手链", "耳环", "耳坠", "耳钉", "戒指", "指环",
    "胸针", "吊坠", "手镯", "头饰", "脚链", "颈饰",
    "首饰", "饰品", "珠宝",
]

# 珍珠饰品上下文词：必须至少命中一个，证明是饰品/珠宝行业
# 与"珍珠"配合使用，确保不是药品、食材、比喻等非饰品语境
JEWELRY_CONTEXT_WORDS = [
    # 饰品品类（与珍珠组合的具体品类）
    "项链", "手链", "耳环", "戒指", "胸针", "吊坠", "手镯", "头饰", "脚链",
    "耳坠", "耳钉", "指环", "颈饰", "耳饰", "手饰", "脚饰",
    # 饰品通用词
    "饰品", "首饰", "珠宝", "配饰", "镶嵌",
    # 佩戴/展示场景
    "佩戴", "穿戴", "穿搭", "造型", "盛装", "礼服", "红毯", "出席",
    # 行业活动/品牌场景
    "珠宝展", "珠宝节", "饰品展", "时尚", "高定", "定制",
    "联名", "代言", "新品发布", "系列", "旗舰店",
    # 交易/市场场景
    "零售", "销量", "市场", "消费", "出口", "进口",
    "拍卖", "苏富比", "佳士得",
    # 工艺/材质
    "K金", "18K", "14K", "铂金", "黄金", "彩金", "镀金",
    "镶嵌", "钻石", "宝石", "翡翠", "彩宝", "祖母绿",
    # 行业特有词
    "养殖", "蚌", "珠母", "育苗", "插核",
    "产区", "产量", "进出口", "原石",
]

# 非饰品行业排除词：命中则直接排除（即使含"珍珠"字样）
# 覆盖：药品/医疗、化妆品/护肤品、食材/食品、日用品、动植物、农业等
NON_JEWELRY_EXCLUDE_WORDS = [
    # 药品/医疗
    "药膏", "药片", "药丸", "药用", "药材", "滴眼液",
    "珍珠疹", "珍珠瘤", "珍珠眼", "眼药水", "眼膏",
    "药监局", "美白剂", "药准字",
    # 化妆品/护肤品
    "面膜", "乳液", "面霜", "精华液", "洗面奶", "护肤品",
    "化妆品", "口红", "粉底", "眼影", "唇釉", "美容",
    "珍珠粉", "珍珠膏",
    # 食材/食品
    "奶茶", "珍珠奶茶", "奶茶店", "饮品", "茶饮",
    "食用", "食材", "烹饪", "烘焙", "甜品",
    # 日用品
    "牙膏", "牙刷", "香皂", "肥皂", "洗手液",
    "洗衣液", "洗衣粉", "洗洁精",
    # 珍珠+动植物复合词（非饰品）
    "珍珠枣", "珍珠梅", "珍珠菜", "珍珠草", "珍珠番茄",
    "珍珠鸡", "珍珠鸟", "珍珠鱼", "珍珠米", "珍珠棉",
    "珍珠岩", "珍珠果", "珍珠粟", "珍珠伞",
    # 农业/种植业
    "种植", "栽植", "栽培", "农户", "果园", "农产品",
    "果品", "增产", "增收", "致富", "合作社", "油桃",
    "油桃", "核桃", "猕猴桃",
    # 非饰品行业文章标题关键词
    "数码相机", "选购指南", "选购榜", "相机评测",
    "AI提示词", "提示词分享", "AI绘画",
    "排行榜", "推荐榜",
]

# 比喻用法正则：检测"珍珠"被用作文学比喻而非饰品
# 例如："记忆里的珍珠"、"人生的珍珠"、"珍珠般的智慧"
METAPHOR_PATTERNS = [
    re.compile(r"(?:记忆|回忆|人生|时间|历史|岁月|童年|青春|梦想|希望|往事|故事|智慧|思想)\s*(?:里|中|之|的)?\s*珍珠"),
    re.compile(r"珍珠\s*(?:般|一样|似的|般的)"),
    re.compile(r"珍珠\s*(?:光芒|光辉|光彩|品质|精神|气质|灵魂)"),
]

# 名气信号词（珍珠相关品牌/名人/机构）
# 作用：作为饰品行业上下文的替代信号——命中即视为饰品行业内容
# 注意：仍需先通过 Layer 3（非饰品排除）和 Layer 5（含"珍珠"字样）
FAMOUS_BRANDS = [
    # 珍珠专业品牌（强相关）
    "Mikimoto", "御木本", "TASAKI", "塔思琦",
    "京润珍珠", "阮仕珍珠", "天使之泪", "千足珍珠",
    "黛米", "欧诗漫", "山下湖", "佳丽珍珠",
    # 综合珠宝品牌（含珍珠产品线）
    "卡地亚", "Cartier", "蒂芙尼", "Tiffany", "宝格丽", "Bulgari",
    "梵克雅宝", "Van Cleef", "伯爵", "Piaget",
    "海瑞温斯顿", "Harry Winston", "格拉夫", "Graff",
    "Pandora", "潘多拉", "APM", "POMELLATO", "CINDY CHAO",
    "周大福", "周生生", "老凤祥", "六福珠宝", "周宝生",
    "金至尊", "谢瑞麟", "潮宏基", "老庙", "明牌",
    "TTF", "轩灵", "CYoung",
]

# 行业名人/IP（同样作为饰品行业上下文的替代信号）
FAMOUS_PEOPLE = [
    # 珠宝行业KOL/设计师
    "郭培", "Guo Pei", "兰玉", "刘嘉玲", "赵雅芝",
    # 明星代言/佩戴高频
    "杨幂", "赵丽颖", "范冰冰", "章子怡", "刘亦菲",
    "周也", "白鹿", "虞书欣", "迪丽热巴", "古力娜扎",
    # 拍卖/展览相关
    "苏富比", "Sotheby", "佳士得", "Christie",
    "保利", "北京保利", "中国嘉德", "嘉德",
    # 大型展会
    "进博会", "消博会", "珠博会", "珠宝展",
    # 行业协会
    "中宝协", "GAC", "中国珠宝玉石首饰行业协会",
]

# 负面信息筛选词（用于识别行业乱象类内容）
# 命中后需进一步判断传播度：是否权威媒体、是否含强信号词
NEGATIVE_SIGNAL_WORDS = [
    "诈骗", "骗局", "欺诈", "售假", "造假", "虚假",
    "套路", "乱象", "潜规则", "暴利", "水很深",
    "跑路", "维权", "投诉", "曝光", "查处", "通报",
    "立案", "调查", "退市", "关注函", "处罚", "罚款",
    "真假", "以次充好", "染色", "漂白", "假冒",
]

# 负面信息传播度强信号（命中任一即视为有传播度）
# 用于过滤零散个人投诉/小账号吐槽
NEGATIVE_IMPACT_WORDS = [
    "警方", "公安", "刑拘", "抓获", "团伙", "涉案",
    "亿元", "万元", "千万", "百万元",
    "央视", "新华社", "人民日报", "光明日报", "经济日报",
    "省公安", "监管部门", "证监会", "市监", "海关",
    "立案调查", "强制退市", "关注函", "集群战役",
    "全链条", "收网", "排查", "约谈",
]

# 权威媒体来源（用于负面信息传播度判断）
AUTHORITIVE_SOURCES = [
    "新华社", "人民日报", "央视", "CCTV", "光明日报", "经济日报",
    "中新网", "中国新闻网", "环球时报", "参考消息",
    "财经", "证券", "21世纪", "第一财经", "界面新闻",
    "南方日报", "南方周末", "南方都市报", "广州日报",
    "北京日报", "北京青年报", "新京报", "澎湃新闻",
    "新华网", "人民网", "央视网", "中国网",
]

# 地名误判排除：标题含"珍珠河/港/岛/镇/路"等且无珠宝首饰词时排除
# 覆盖"珍珠河最热""珍珠路2号"等地址误判
PLACE_NAME_PATTERN = re.compile(r"珍珠[河港岛镇村湾半岛山路大街]")

# 主题分类词典：关键词 -> (主题key)
TOPIC_RULES = [
    ("policy",   ["政策", "通知", "公告", "规范", "标准", "海关", "自然资源部",
                  "税", "自贸港", "监管", "法规", "团体标准", "行业协会"]),
    ("upstream", ["养殖", "蚌", "Akoya", "淡水", "海水", "产量", "产区",
                  "诸暨", "北海", "育苗", "插核", "珠母", "原料"]),
    ("expo",     ["珠宝展", "博览会", "展览", "展会", "大会", "论坛", "盛典",
                  "峰会", "消博会", "进博会", "开幕式", "活动"]),
    ("kol",      ["明星", "代言", "佩戴", "同款", "带货", "直播",
                  "红毯", "综艺", "网红", "KOL", "博主", "热搜",
                  "造型", "穿搭", "礼服", "少女", "出席", "惊艳", "look", "造形"]),
    ("brand",    ["发布", "新品", "系列", "联名", "旗舰店", "首发",
                  "周大福", "御木本", "Mikimoto", "TASAKI", "京润", "阮仕", "老凤祥"]),
    ("market",   ["价格", "销量", "增长", "出口", "进口", "数据", "报告",
                  "指数", "万亿", "亿元", "市场", "消费", "零售"]),
]
TOPIC_META = {
    "policy":   ("🏛️", "行业政策"),
    "upstream": ("🔬", "产业上游"),
    "expo":     ("🎪", "展会活动"),
    "kol":      ("💰", "明星带货"),
    "brand":    ("💎", "品牌新品"),
    "market":   ("📈", "市场动态"),
    "other":    ("📰", "行业资讯"),
}

# 数据源 URL
# 中宝协首页为 JS 跳转页，真实内容在 home_page；新闻文章链接含 element_id= 参数
GAC_BASE = "https://www.jewellery.org.cn/jewelleryorgwebsite/sub/home_page"
# 注意：必须用 www.bing.com 且带 form=PTFNR + qft=interval，否则会被重定向到必应首页
BING_NEWS_URL = "https://www.bing.com/news/search"
TOPHUB_WEIBO_URL = "https://tophub.today/n/KqndgxeLl9"  # 微博热搜

# 摘要净化词
SUMMARY_NOISE = [
    "小编", "点击", "关注", "扫码", "下载APP", "查看更多", "网友纷纷",
    "原标题", "来源：", "责任编辑", "声明：", "推荐阅读",
]


# ── 时间工具 ──────────────────────────────────────────────
def now_bj() -> datetime:
    """当前北京时间（naive datetime，便于与解析出的时间统一比较）"""
    if BJT is not None:
        return datetime.now(BJT).replace(tzinfo=None)
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


def parse_relative_time(text: str, base: datetime) -> datetime | None:
    """解析相对时间文本：'X小时前' 'X分钟前' 'X天前' '昨天' '前天' '今天'"""
    if not text:
        return None
    text = text.strip()
    # "前"字可选：Bing 返回 "20 小时"（无"前"），搜狗返回 "3小时前"（带"前"）
    m = re.search(r"(\d+)\s*(分钟|分|小时|时|天|日)\s*前?", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit in ("分钟", "分"):
            return base - timedelta(minutes=n)
        if unit in ("小时", "时"):
            return base - timedelta(hours=n)
        if unit in ("天", "日"):
            return base - timedelta(days=n)
    if "昨天" in text:
        return base - timedelta(days=1)
    if "前天" in text:
        return base - timedelta(days=2)
    if "今天" in text or "刚刚" in text:
        return base
    return None


def parse_absolute_time(text: str) -> datetime | None:
    """解析绝对时间：'2026-08-07 10:30:00' / '2026年8月7日' / '2026-08-07'"""
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y年%m月%d日 %H:%M", "%Y年%m月%d日", "%Y.%m.%d"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    # 从文本中提取日期片段
    m = re.search(r"(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


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


def head_check(url: str, timeout: int = 8) -> bool:
    """HEAD 请求校验链接可访问性；部分站点不支持 HEAD 时回退 GET"""
    try:
        r = requests.head(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code < 400:
            return True
        # 某些站点 HEAD 返回 405，回退 GET
        if r.status_code in (405, 403):
            r2 = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
            ok = r2.status_code < 400
            r2.close()
            return ok
        return False
    except Exception:
        return False


# ── 链接真实性解析 ────────────────────────────────────────
def resolve_real_url(url: str) -> str:
    """对搜索引擎跳转链接跟随重定向，获取真实源 URL"""
    if not url:
        return ""
    # 搜狗跳转链接：news.sogou.com/link?url=...
    if "news.sogou.com" in url or "sogou" in urlparse(url).netloc:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
            if r.url and "sogou" not in urlparse(r.url).netloc:
                return r.url
        except Exception:
            pass
    return url


def is_valid_news_url(url: str) -> bool:
    """URL 基础合法性校验：非空、http(s)、非搜索引擎自身跳转页"""
    if not url or not url.startswith(("http://", "https://")):
        return False
    host = urlparse(url).netloc.lower()
    # 排除仍指向搜索引擎的链接
    bad_hosts = ["bing.com", "baidu.com", "sogou.com", "google.com",
                 "tophub.today", "so.com"]
    return not any(h in host for h in bad_hosts)


# ── 数据源：中宝协官网（权威行业源）──────────────────────
def parse_gac_news() -> list[dict]:
    """抓取中国珠宝玉石首饰行业协会官网首页新闻列表"""
    results = []
    resp = safe_get(GAC_BASE)
    if not resp:
        logger.warning("中宝协官网请求失败")
        return results
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # 提取所有指向文章详情页的链接（含 element_id= 的才是文章，纯 label_id 是分类页）
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "element_id=" not in href:
            continue
        full_url = urljoin(GAC_BASE, href)
        if full_url in seen:
            continue
        seen.add(full_url)

        title = a.get_text(strip=True)
        if not title or len(title) < 6:
            continue
        if any(fw in title for fw in FILTER_WORDS):
            continue

        results.append({
            "title": title,
            "url": full_url,
            "summary": "",
            "source": "中宝协",
            "_need_detail": True,  # 标记需要抓详情页补全时间与摘要
        })

    logger.info(f"中宝协列表页获取 {len(results)} 条候选")

    # 抓取详情页补全时间与摘要（限制数量，避免请求过多）
    enriched = []
    for item in results[:25]:
        detail = _enrich_gac_detail(item)
        if detail:
            enriched.append(detail)
        time.sleep(0.3)
    logger.info(f"中宝协详情页补全后保留 {len(enriched)} 条")
    return enriched


def _enrich_gac_detail(item: dict) -> dict | None:
    """抓取中宝协文章详情页，提取发布时间与正文摘要"""
    resp = safe_get(item["url"])
    if not resp:
        return item  # 保留但无时间
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # 解析发布时间：如 "2026-05-21 1:3:26"
    pub_time = None
    m = re.search(r"(20\d{2}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{1,2}(?::\d{1,2})?)", text)
    if m:
        pub_time = parse_absolute_time(m.group(1))
    item["publish_time"] = pub_time

    # 提取正文摘要：优先 meta description，其次正文前 200 字
    desc = ""
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()
    if not desc:
        # 取正文主体段落
        content_div = soup.find("div", class_=re.compile("content|detail|article|text", re.I))
        paras = (content_div or soup).find_all("p")
        desc = " ".join(p.get_text(strip=True) for p in paras if p.get_text(strip=True))
    item["summary"] = desc[:300] if desc else ""
    return item


# ── 数据源：Bing News 搜索（主力综合源）──────────────────
def parse_bing_news(keyword: str, interval: str = "7") -> list[dict]:
    """
    抓取 Bing News 搜索结果。
    interval: "7"=24小时内, "8"=7天内, "9"=30天内
    """
    results = []
    params = f"?q={quote(keyword)}&qft=interval%3d%22{interval}%22&form=PTFNR"
    url = BING_NEWS_URL + params
    resp = safe_get(url)
    if not resp:
        return results
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    base = now_bj()
    # Bing News 结果项：多种选择器兼容
    items = (soup.select(".news-card") or soup.select(".t_t")
             or soup.select("[data-author]") or soup.select(".newsitem"))
    if not items:
        # 兜底：找所有含链接的 news 容器
        items = soup.select("div.itm")

    for it in items:
        try:
            a = it.select_one("a.title") or it.select_one("a.tilk") or it.select_one("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 6:
                continue
            if any(fw in title for fw in FILTER_WORDS):
                continue

            link = a.get("href", "")
            if link and not link.startswith("http"):
                link = urljoin("https://cn.bing.com", link)

            snippet = ""
            sn = it.select_one(".snippet") or it.select_one(".t_t")
            if sn:
                snippet = sn.get_text(strip=True)

            # Bing 的来源与时间通常合并在 .source 元素中，如 "腾讯网20 小时"
            source = "Bing"
            pub_time = None
            src_el = it.select_one(".source") or it.select_one(".t_A")
            if src_el:
                src_text = src_el.get_text(strip=True)
                # 从末尾提取相对时间，剩余部分作为来源名
                m = re.search(r'(\d+\s*(?:分钟|分|小时|时|天|日))\s*前?$', src_text)
                if m:
                    pub_time = parse_relative_time(m.group(1), base)
                    source = src_text[:m.start()].strip() or "Bing"
                else:
                    source = src_text[:30]

            results.append({
                "title": title,
                "url": link,
                "summary": snippet,
                "source": source,
                "publish_time": pub_time,
            })
        except Exception as e:
            logger.debug(f"解析 Bing 条目失败: {e}")

    return results


# ── 数据源：今日热榜（微博热搜，社交热点源）──────────────
def parse_tophub() -> list[dict]:
    """抓取今日热榜微博热搜节点，筛选珍珠/珠宝相关话题"""
    results = []
    resp = safe_get(TOPHUB_WEIBO_URL)
    if not resp:
        logger.warning("今日热榜请求失败")
        return results
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    base = now_bj()
    # 热榜条目：表格行或列表项
    rows = soup.select("table tr") or soup.select(".item") or soup.select("tr")
    for tr in rows:
        try:
            a = tr.select_one("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 4:
                continue
            # 仅保留与珠宝/奢侈品/名人相关的热搜
            hot_keywords = ["珍珠", "珠宝", "项链", "首饰", "饰品", "宝石", "钻石", "翡翠",
                           "黄金", "腕表", "手表", "奢侈", "品牌", "代言",
                           "卡地亚", "蒂芙尼", "宝格丽", "周大福", "Pandora",
                           "TASAKI", "Mikimoto", "珍珠手链", "珍珠项链"]
            if not any(kw in title for kw in hot_keywords):
                continue
            link = a.get("href", "")
            if link and not link.startswith("http"):
                link = urljoin("https://tophub.today", link)

            # 热度数值
            hot_text = ""
            hot_el = tr.select_one(".hot") or tr.select_one("td:last-child")
            if hot_el:
                hot_text = hot_el.get_text(strip=True)

            results.append({
                "title": f"微博热搜：{title}",
                "url": link,
                "summary": f"微博热搜话题{('，热度' + hot_text) if hot_text else ''}",
                "source": "微博热搜",
                "publish_time": base,  # 热榜视为当前热点
            })
        except Exception as e:
            logger.debug(f"解析热榜条目失败: {e}")

    logger.info(f"今日热榜筛选出 {len(results)} 条珍珠珠宝相关热搜")
    return results


# ── 数据源：搜狗新闻（备用）──────────────────────────────
def parse_sogou_news(keyword: str) -> list[dict]:
    """搜狗新闻搜索（备用数据源，仅主力源失败时启用）"""
    results = []
    url = f"https://news.sogou.com/news?query={quote(keyword)}&sort=1"
    resp = safe_get(url)
    if not resp:
        return results
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    base = now_bj()
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
            # 关键修复：跟随重定向拿真实 URL
            real_link = resolve_real_url(link)

            summary = ""
            s_tag = item.select_one("p.txt-info") or item.select_one(".txt-info")
            if s_tag:
                summary = s_tag.get_text(strip=True)[:200]

            source = "搜狗新闻"
            src_tag = item.select_one(".news-from") or item.select_one(".from")
            if src_tag:
                src_text = src_tag.get_text(strip=True)
                # 搜狗来源文本含时间，尝试解析
                pub_time = parse_relative_time(src_text, base) or parse_absolute_time(src_text)
                source = src_text[:20]
            else:
                pub_time = None

            results.append({
                "title": title,
                "url": real_link,
                "summary": summary,
                "source": source,
                "publish_time": pub_time,
            })
        except Exception as e:
            logger.debug(f"解析搜狗条目失败: {e}")
    return results


# ── 去重与聚合 ────────────────────────────────────────────
def normalize_title(t: str) -> str:
    """标题归一化：去空格标点，便于相似度比较"""
    return re.sub(r"[\s\-_\|：:，,。.！!？?【】\[\]()（）]+", "", t or "")


def deduplicate(items: list[dict]) -> list[dict]:
    """基于标题 MD5 去重"""
    seen = set()
    unique = []
    for item in items:
        h = hashlib.md5(normalize_title(item["title"]).encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(item)
    return unique


def merge_similar(items: list[dict]) -> list[dict]:
    """合并标题高度相似的同事件报道（子串包含关系）"""
    items = sorted(items, key=lambda x: len(x.get("summary", "")), reverse=True)
    kept = []
    for item in items:
        nt = normalize_title(item["title"])
        merged = False
        if len(nt) > 8:
            for k in kept:
                kt = normalize_title(k["title"])
                if len(kt) > 8 and (nt in kt or kt in nt):
                    # 合并：保留更详摘要 + 更早时间
                    if len(item.get("summary", "")) > len(k.get("summary", "")):
                        k["summary"] = item["summary"]
                    pt = item.get("publish_time")
                    if pt and (not k.get("publish_time") or pt < k["publish_time"]):
                        k["publish_time"] = pt
                    k["_sources"] = k.get("_sources", [k.get("source", "")]) + [item.get("source", "")]
                    merged = True
                    break
        if not merged:
            kept.append(item)
    return kept


# ── 过滤 ──────────────────────────────────────────────────
def is_high_impact_negative(item: dict, combined_text: str) -> bool:
    """
    判断负面信息是否具备足够传播度（仅保留有传播度、引发广泛讨论、
    影响消费者整体信任度的负面话题）。
    条件：负面信号词命中 AND (传播度强信号词命中 OR 权威媒体来源)
    """
    # 必须先命中负面信号词，才算负面信息
    if not any(w in combined_text for w in NEGATIVE_SIGNAL_WORDS):
        return False  # 不是负面信息，交给正常流程

    # 是负面信息，需进一步验证传播度
    has_impact = any(w in combined_text for w in NEGATIVE_IMPACT_WORDS)
    source = item.get("source", "")
    has_authority = any(a in source for a in AUTHORITIVE_SOURCES)

    return has_impact or has_authority


def filter_relevant(items: list[dict]) -> list[dict]:
    """
    珍珠饰品品类精准过滤 + 负面信息传播度筛选。

    多层过滤规则（按顺序执行）：
    1. 噪声词过滤：过滤奶茶、比特币、乐高游戏等明确无关内容
    2. 域名排除：过滤百科、电商、医疗等非新闻来源
    3. ★ 非饰品行业排除：命中药品/化妆品/食材/日用品/动植物/农业关键词直接剔除
       - 例：珍珠药膏（药品）、珍珠面膜（化妆品）、珍珠枣（水果）、珍珠鸡（动物）
       - 覆盖非饰品标题关键词：数码相机、AI提示词、选购榜等
    4. 地名误判排除：珍珠路/河/港/岛等地址类误判
    5. ★ 核心规则1：标题必须含"珍珠"字样（PEARL_CORE_WORDS 在标题中命中）
       - 仅摘要含"珍珠"但标题不含的不通过（避免相机评测等误入）
       - 例外：标题含珍珠专业品牌（Mikimoto/TASAKI/京润珍珠等）也算通过
    6. ★ 核心规则2：标题或摘要含饰品/珠宝行业上下文（JEWELRY_CONTEXT_WORDS 命中）
       - 品类词：项链、手链、耳环、戒指、胸针...
       - 场景词：佩戴、穿搭、红毯、珠宝展、拍卖...
       - 材质词：K金、铂金、黄金、钻石、宝石...
       - 品牌/名人：FAMOUS_BRANDS + FAMOUS_PEOPLE 命中即可通过
    7. ★ 比喻用法检测：过滤"记忆里的珍珠""珍珠般的智慧"等文学比喻
    8. 负面信息筛选：必须命中负面信号词 AND 满足传播度条件
    """
    # 预编译
    pearl_re = re.compile("|".join(re.escape(w) for w in PEARL_CORE_WORDS), re.I)
    context_re = re.compile("|".join(re.escape(w) for w in JEWELRY_CONTEXT_WORDS), re.I)
    fame_words = FAMOUS_BRANDS + FAMOUS_PEOPLE
    fame_re = re.compile("|".join(re.escape(w) for w in fame_words), re.I)
    negative_re = re.compile("|".join(re.escape(w) for w in NEGATIVE_SIGNAL_WORDS), re.I)
    exclude_re = re.compile("|".join(re.escape(w) for w in NON_JEWELRY_EXCLUDE_WORDS), re.I)

    filtered = []
    stats = {
        "noise": 0, "domain": 0, "non_jewelry": 0,
        "place_name": 0, "no_pearl_title": 0, "no_context": 0,
        "metaphor": 0, "negative_low": 0,
    }
    for item in items:
        title = item.get("title", "")
        summary = item.get("summary", "")
        source = item.get("source", "")
        url = item.get("url", "")

        combined_text = f"{title} {summary}"
        combined_lower = f"{title} {summary} {source} {url}".lower()

        # ── Layer 1: 噪声词过滤 ──
        if any(fw in combined_text for fw in FILTER_WORDS):
            stats["noise"] += 1
            continue

        # ── Layer 2: 域名排除 ──
        if any(ex in combined_lower for ex in EXCLUDE_DOMAINS):
            stats["domain"] += 1
            continue

        # ── Layer 3: ★ 非饰品行业排除（药品/化妆品/食材/动植物/农业/非饰品标题）──
        if exclude_re.search(combined_text):
            stats["non_jewelry"] += 1
            continue

        # ── Layer 4: 地名误判排除 ──
        if PLACE_NAME_PATTERN.search(combined_text):
            text_without_places = PLACE_NAME_PATTERN.sub("", combined_text)
            if not pearl_re.search(text_without_places):
                stats["place_name"] += 1
                continue
            if not context_re.search(text_without_places):
                stats["place_name"] += 1
                continue

        # ── Layer 5: ★ 标题必须含"珍珠"字样 或 饰品品类词 或 珍珠品牌 ──
        # 珍珠必须在标题中出现，或标题含明确饰品品类（项链/耳环等）或品牌名
        # 避免"数码相机评测"等标题无珍珠、仅在摘要提及的文章误入
        has_pearl_in_title = bool(pearl_re.search(title))
        has_jewelry_in_title = any(w in title for w in TITLE_JEWELRY_WORDS)
        has_fame_in_title = bool(fame_re.search(title))
        if not (has_pearl_in_title or has_jewelry_in_title or has_fame_in_title):
            stats["no_pearl_title"] += 1
            continue

        # ── Layer 6: ★ 标题或摘要含饰品/珠宝行业上下文 ──
        has_context = bool(context_re.search(combined_text))
        has_fame = bool(fame_re.search(combined_text))
        if not has_context and not has_fame:
            stats["no_context"] += 1
            continue

        # ── Layer 7: ★ 比喻用法检测 ──
        is_metaphor = any(p.search(combined_text) for p in METAPHOR_PATTERNS)
        if is_metaphor:
            stats["metaphor"] += 1
            continue

        # ── Layer 8: 负面信息传播度筛选 ──
        is_negative = bool(negative_re.search(combined_text))
        if is_negative:
            if not is_high_impact_negative(item, combined_text):
                stats["negative_low"] += 1
                continue
            item["_is_negative"] = True

        if has_fame:
            item["_has_fame"] = True

        filtered.append(item)

    logger.info(
        f"相关性过滤: {len(items)} -> {len(filtered)} 条 | "
        f"噪声{stats['noise']} 域名{stats['domain']} "
        f"非饰品{stats['non_jewelry']} 地名{stats['place_name']} "
        f"标题无珍珠{stats['no_pearl_title']} 无上下文{stats['no_context']} "
        f"比喻{stats['metaphor']} 低传播度{stats['negative_low']}"
    )
    return filtered


def sort_by_popularity(items: list[dict]) -> list[dict]:
    """
    按热度/传播度排序：
    - 负面信息优先按传播度排序（强信号词多的在前）
    - 名气信号词命中的优先
    - 有发布时间的优先（越新越前）
    """
    def score(item: dict) -> int:
        s = 0
        # 名气加分
        if item.get("_has_fame"):
            s += 10
        # 负面传播度加分（命中越多传播度强信号词越高）
        if item.get("_is_negative"):
            text = f"{item.get('title', '')} {item.get('summary', '')}"
            s += sum(3 for w in NEGATIVE_IMPACT_WORDS if w in text)
            s += 20  # 负面热点本身加分
        # 有时间加分
        if item.get("publish_time"):
            s += 5
        return s

    return sorted(items, key=score, reverse=True)


def filter_by_time(items: list[dict], hours: int) -> list[dict]:
    """时效过滤：保留 publish_time 在 hours 小时内的条目；无时间的视为未知，保留但降权"""
    base = now_bj()
    in_window = []
    no_time = []
    for item in items:
        pt = item.get("publish_time")
        if pt is None:
            no_time.append(item)
            continue
        try:
            age = base - pt
            if timedelta(0) <= age <= timedelta(hours=hours):
                in_window.append(item)
        except Exception:
            no_time.append(item)
    # 有时间的优先；时间未知的放最后兜底
    return in_window + no_time


# ── 主题分类与摘要整理 ───────────────────────────────────
def classify_topic(item: dict) -> str:
    """基于关键词规则判定主题"""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    for topic, words in TOPIC_RULES:
        if any(w in text for w in words):
            return topic
    return "other"


def extract_key_numbers(text: str) -> list[str]:
    """提取关键数字（价格/销量/增长率等），用于摘要前置加粗"""
    if not text:
        return []
    patterns = [
        r"\d+(?:\.\d+)?\s*亿元",
        r"\d+(?:\.\d+)?\s*亿",
        r"\d+(?:\.\d+)?\s*万[元件吨]?",
        r"\d+(?:\.\d+)?\s*元",
        r"\d+(?:\.\d+)?\s*%",
        r"\d+(?:\.\d+)?\s*倍",
        r"\d+(?:\.\d+)?\s*件",
    ]
    found = []
    for p in patterns:
        for m in re.finditer(p, text):
            v = m.group(0).strip()
            if v and v not in found:
                found.append(v)
    return found[:5]


def refine_summary(text: str) -> str:
    """摘要净化：去广告词、压缩空白、限 120 字"""
    if not text:
        return ""
    s = text
    for noise in SUMMARY_NOISE:
        s = s.replace(noise, "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120]


def enrich_item(item: dict) -> dict:
    """为单条新闻补充主题、关键数字、精简摘要"""
    item["topic"] = classify_topic(item)
    full_text = f"{item.get('title', '')} {item.get('summary', '')}"
    numbers = extract_key_numbers(full_text)
    refined = refine_summary(item.get("summary", ""))
    # 关键数字前置加粗
    if numbers and refined:
        nums_str = "、".join(f"**{n}**" for n in numbers[:3])
        # 若摘要已含数字，不再重复前缀；否则前置
        if not any(n in refined for n in numbers[:1]):
            refined = f"关键数据：{nums_str}。{refined}"
    item["summary_refined"] = refined
    return item


def format_time(pub_time) -> str:
    """格式化发布时间为展示文本"""
    if pub_time is None:
        return "时间不详"
    try:
        base = now_bj()
        delta = base - pub_time
        if delta < timedelta(hours=1):
            return f"{int(delta.total_seconds() // 60)}分钟前"
        if delta < timedelta(hours=24):
            return f"{int(delta.total_seconds() // 3600)}小时前"
        if delta < timedelta(hours=48):
            return "昨天"
        return pub_time.strftime("%m-%d")
    except Exception:
        return "时间不详"


# ── 降级选择 ──────────────────────────────────────────────
def select_items_with_fallback(items: list[dict]) -> tuple[list[dict], str]:
    """
    返回 (最终条目列表, 模式)。
    模式：normal(48h内>=3条) / fallback(48h内不足，补充7d) / fallback_only(48h空，用7d) / empty
    """
    hot = filter_by_time(items, HOT_WINDOW_HOURS)
    # 仅保留有真实时间的条目作为 hot 主体（filter_by_time 把无时间的放最后，需剔除）
    base = now_bj()
    hot_timed = [x for x in hot if x.get("publish_time") is not None
                 and (base - x["publish_time"]) <= timedelta(hours=HOT_WINDOW_HOURS)]

    if len(hot_timed) >= HOT_MIN_COUNT:
        return hot_timed[:NORMAL_MAX_COUNT], "normal"

    # 不足，降级到 7d
    fb = filter_by_time(items, FALLBACK_WINDOW_HOURS)
    fb_timed = [x for x in fb if x.get("publish_time") is not None
                and (base - x["publish_time"]) <= timedelta(hours=FALLBACK_WINDOW_HOURS)]

    if hot_timed:
        # 48h内有少量，补充7d凑足
        merged = hot_timed + [x for x in fb_timed if x not in hot_timed]
        return merged[:FALLBACK_MAX_COUNT], "fallback"

    if fb_timed:
        return fb_timed[:FALLBACK_MAX_COUNT], "fallback_only"

    # 7d 内也没有，退而求其次用无时间但相关度高的条目
    if items:
        return items[:FALLBACK_MAX_COUNT], "fallback_only"
    return [], "empty"


# ── 消息构建 ──────────────────────────────────────────────
def build_message(items: list[dict], mode: str, date_str: str) -> tuple[str, str]:
    """构建钉钉 Markdown 日报消息"""
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    wd = weekdays[now_bj().weekday()]
    title = f"💎 珍珠珠宝日报 - {date_str}"

    lines = [f"## 💎 珍珠珠宝日报\n"]
    lines.append(f"**{date_str} {wd}** · 共精选 **{len(items)}** 条\n")

    if mode == "fallback":
        lines.append("⚠️ 近48小时无重大热点，以下为近期精选\n")
    elif mode == "fallback_only":
        lines.append("⚠️ 近48小时无重大热点，以下为近期行业资讯精选\n")
    elif mode == "empty":
        lines.append("💎 今日暂无重大珍珠珠宝资讯，行业平稳运行\n")
        lines.append("\n---\n*由珍珠珠宝新闻机器人自动生成 · 数据来源: 中宝协 / Bing / 微博热搜*")
        return title, "\n".join(lines)

    lines.append("---\n")

    # 按主题分组
    by_topic: dict[str, list[dict]] = {}
    for it in items:
        by_topic.setdefault(it.get("topic", "other"), []).append(it)

    # 主题展示顺序
    topic_order = ["policy", "upstream", "expo", "kol", "brand", "market", "other"]
    for topic in topic_order:
        if topic not in by_topic:
            continue
        emoji, name = TOPIC_META[topic]
        group = by_topic[topic]
        lines.append(f"### {emoji} {name}\n")
        for it in group[:2]:  # 每组最多2条
            t = it.get("title", "")
            u = it.get("url", "")
            summary = it.get("summary_refined", "") or refine_summary(it.get("summary", ""))
            src = it.get("source", "")
            t_str = format_time(it.get("publish_time"))

            if u and is_valid_news_url(u):
                lines.append(f"▶ [{t}]({u})")
            else:
                lines.append(f"▶ {t}")
            if summary:
                lines.append(f"  {summary}")
            lines.append(f"  📰 {src} · {t_str}\n")
        lines.append("")

    lines.append("---")
    lines.append("*数据来源: 中宝协 / Bing News / 微博热搜 · 由珍珠珠宝新闻机器人精选*")

    content = "\n".join(lines)
    if len(content) > DINGTALK_MAX_LEN:
        content = content[:DINGTALK_MAX_LEN] + "\n\n...(内容过长已截断)"
    return title, content


# ── 钉钉推送 ──────────────────────────────────────────────
def send_dingtalk(webhook_url: str, title: str, content: str) -> bool:
    """钉钉机器人推送（带3次指数退避重试）"""
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": content},
    }
    for attempt in range(3):
        try:
            resp = requests.post(
                webhook_url, json=payload,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            result = resp.json()
            if result.get("errcode") == 0:
                logger.info(f"钉钉消息发送成功 (第{attempt+1}次尝试)")
                return True
            # errcode 130101 等为频率限制，需要等待
            if result.get("errcode") in (130101, 9001):
                logger.warning(f"钉钉频率限制，等待后重试: {result}")
                time.sleep(5 * (attempt + 1))
                continue
            logger.error(f"钉钉发送失败: {result}")
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            logger.error(f"钉钉发送异常 (第{attempt+1}次): {e}")
            time.sleep(3 * (attempt + 1))
    return False


def send_alert(webhook_url: str, err_msg: str) -> None:
    """异常告警推送，避免完全静默"""
    if not webhook_url:
        return
    title = "⚠️ 珍珠珠宝日报运行异常"
    content = (f"## ⚠️ 运行异常\n\n"
               f"**时间**: {now_bj().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
               f"**错误**: {err_msg[:500]}\n\n"
               f"请检查 GitHub Actions 日志排查问题。")
    try:
        send_dingtalk(webhook_url, title, content)
    except Exception:
        pass


# ── 主流程 ────────────────────────────────────────────────
def collect_news() -> list[dict]:
    """从所有数据源收集新闻"""
    all_items = []

    # 1. 中宝协官网（权威行业源）
    logger.info("=== 抓取中宝协官网 ===")
    try:
        gac = parse_gac_news()
        all_items.extend(gac)
        logger.info(f"中宝协获取 {len(gac)} 条")
    except Exception as e:
        logger.error(f"中宝协抓取异常: {e}")

    # 2. Bing News（主力综合源）—— 4组关键词覆盖全行业
    logger.info("=== 抓取 Bing News ===")
    bing_keywords = (KEYWORDS_CORE + KEYWORDS_INDUSTRY
                     + KEYWORDS_EVENT + KEYWORDS_CELEBRITY)
    for kw in bing_keywords:
        try:
            items = parse_bing_news(kw, interval="8")  # 7天内，覆盖降级场景
            all_items.extend(items)
            if items:
                logger.info(f"  Bing[{kw}] 获取 {len(items)} 条")
        except Exception as e:
            logger.warning(f"  Bing[{kw}] 异常: {e}")
        time.sleep(0.6)

    # 3. 今日热榜（社交热点）
    logger.info("=== 抓取今日热榜 ===")
    try:
        th = parse_tophub()
        all_items.extend(th)
        logger.info(f"今日热榜获取 {len(th)} 条")
    except Exception as e:
        logger.warning(f"今日热榜异常: {e}")

    # 4. 搜狗新闻（备用：仅在主力源不足时启用）
    if len(all_items) < 10:
        logger.info("=== 主力源不足，启用搜狗备用 ===")
        for kw in KEYWORDS_CORE[:2]:
            try:
                items = parse_sogou_news(kw)
                all_items.extend(items)
                logger.info(f"  搜狗[{kw}] 获取 {len(items)} 条")
            except Exception as e:
                logger.warning(f"  搜狗[{kw}] 异常: {e}")
            time.sleep(1.5)

    logger.info(f"总计收集 {len(all_items)} 条")

    # 去重 -> 相关性过滤（含负面传播度筛选）-> 合并同事件 -> 热度排序
    unique = deduplicate(all_items)
    logger.info(f"去重后 {len(unique)} 条")
    relevant = filter_relevant(unique)
    logger.info(f"相关性过滤后 {len(relevant)} 条")
    merged = merge_similar(relevant)
    logger.info(f"同事件合并后 {len(merged)} 条")
    # 按热度排序：负面热点 + 名气信号 + 时效 综合加权
    merged = sort_by_popularity(merged)
    logger.info(f"热度排序完成")

    # 补充主题/摘要
    enriched = [enrich_item(it) for it in merged]
    return enriched


def main():
    """主入口"""
    webhook_url = os.environ.get("DINGTALK_WEBHOOK")
    try:
        items = collect_news()
        date_str = now_bj().strftime("%Y-%m-%d")

        if not items:
            logger.warning("未收集到任何新闻")
            if webhook_url:
                title, content = build_message([], "empty", date_str)
                send_dingtalk(webhook_url, title, content)
            else:
                print("\n未收集到任何新闻。")
            return

        selected, mode = select_items_with_fallback(items)
        logger.info(f"最终选择 {len(selected)} 条，模式: {mode}")

        title, content = build_message(selected, mode, date_str)

        if webhook_url:
            ok = send_dingtalk(webhook_url, title, content)
            if not ok and mode != "empty":
                send_alert(webhook_url, "钉钉推送重试3次仍失败，请检查webhook或关键词配置")
        else:
            # 测试模式：输出到控制台（Windows GBK 终端需处理 emoji）
            import sys as _sys
            _out = _sys.stdout
            try:
                _out.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
            print("\n" + "=" * 60)
            print(title)
            print("=" * 60)
            print(content)
            print("\n" + "=" * 60)
            print(f"[测试模式] 共 {len(selected)} 条 · 模式: {mode}")

    except Exception as e:
        logger.exception(f"主流程异常: {e}")
        if webhook_url:
            send_alert(webhook_url, f"主流程异常: {e}")
        raise


if __name__ == "__main__":
    main()
