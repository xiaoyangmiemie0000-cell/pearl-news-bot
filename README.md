# 💎 珍珠珠宝新闻自动推送机器人

每天自动从多个渠道抓取珍珠/珠宝相关新闻，按主题分类整理成日报，通过**钉钉机器人**推送到手机。

## 功能特性

- **多源聚合**：中宝协官网（权威行业）+ Bing News（综合）+ 今日热榜微博热搜（社交热点）+ 搜狗（备用）
- **真实链接**：跟随重定向解析真实源 URL，HEAD 校验链接可访问性，过滤失效链接
- **严格时效**：默认仅保留 48 小时内热点；无热点时自动降级到 7 天内精选 2-4 条
- **主题分类**：行业政策 / 产业上游 / 展会活动 / 明星带货 / 品牌新品 / 市场动态，带 emoji 标注
- **关键数据提炼**：自动提取价格、销量、增长率等关键数字并前置加粗
- **稳定推送**：钉钉 3 次指数退避重试 + 全流程异常捕获，失败发告警，避免静默
- **GitHub Actions 双触发**：北京时间 07:00 / 08:00 兜底运行，规避 cron 排队延迟

## 日报样例

```
## 💎 珍珠珠宝日报

**2026-08-07 周四** · 共精选 6 条

---

### 🏛️ 行业政策

▶ [海南自贸港珍珠珠宝产业对接活动成功举办](真实URL)
  加工增值超30%内销免关税，海润珍珠进口580万元原料节省税费 **超120万元**
  📰 中宝协 · 6小时前

---

### 💰 明星带货

▶ [微博热搜：沈梦辰168元珍珠手链引热议](真实URL)
  综艺佩戴平价淡水珍珠手链引发跟风，**168元**售价成焦点
  📰 微博热搜 · 2小时前

---

*数据来源: 中宝协 / Bing News / 微博热搜 · 由珍珠珠宝新闻机器人精选*
```

## 数据源说明

| 数据源 | 类型 | 说明 |
|--------|------|------|
| 中宝协官网 jewellery.org.cn | 权威行业 | 政策公告、产业大会、团体标准、展会资讯，含明确发布时间 |
| Bing News | 综合新闻 | 反爬较轻，支持时间过滤（24h / 7d），结果含真实源 URL |
| 今日热榜(微博热搜) | 社交热点 | 间接覆盖社交平台热点，免密钥免登录 |
| 搜狗新闻 | 备用 | 仅在主力源抓取不足时启用，已修复跳转链接失效问题 |

**关于社交平台的说明**：小红书、抖音有严格反爬和签名验证，在 GitHub Actions 上无法直爬，也无法精确读取点赞/播放量数值。本方案通过今日热榜聚合页间接发现微博热搜中的珍珠珠宝相关话题。如需精确的社交平台互动数据，需接入新榜/蝉妈妈等第三方付费 API。

## 降级推送策略

| 场景 | 行为 |
|------|------|
| 48h 内热点 ≥ 3 条 | 正常推送，按主题分组，最多 8 条 |
| 48h 内热点 1-2 条 | 降级模式，补充 7d 内精选，凑足 2-4 条，开头标注 ⚠️ |
| 48h 内无热点，7d 内有 | 降级模式，推送 7d 内精选 2-4 条 |
| 完全无相关资讯 | 推送"今日暂无珍珠珠宝资讯，行业平稳运行"提示，避免静默 |

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/你的用户名/pearl-news-bot.git
cd pearl-news-bot
```

### 2. 创建钉钉机器人

1. 打开钉钉 → 进入你想接收消息的群
2. 群设置 → 智能群助手 → 添加机器人 → 自定义（通过 Webhook 接入）
3. 安全设置选择「自定义关键词」，填写 `珍珠`
4. 复制生成的 Webhook 地址（形如 `https://oapi.dingtalk.com/robot/send?access_token=xxx`）

### 3. 配置 GitHub Secrets

1. 进入你的 GitHub 仓库页面
2. **Settings** → **Secrets and variables** → **Actions**
3. 点击 **New repository secret**
4. Name 填写 `DINGTALK_WEBHOOK`
5. Value 粘贴刚才复制的钉钉 Webhook 地址
6. 点击 **Add secret** 保存

### 4. 手动测试

1. 进入仓库的 **Actions** 页面
2. 选择左侧「珍珠珠宝新闻日报」
3. 点击 **Run workflow** 手动触发一次
4. 检查钉钉群是否收到消息

### 5. 自动运行

配置完成后，GitHub Actions 会在每天 UTC 23:00（北京 07:00）和 UTC 00:00（北京 08:00）自动运行，双触发兜底确保推送及时。

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 测试模式（不推送，仅打印到控制台）
python pearl_news.py

# 带钉钉推送运行
set DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=你的token
python pearl_news.py
```

## 自定义配置

### 修改关键词

编辑 `pearl_news.py` 中的 `KEYWORDS_CORE` / `KEYWORDS_EVENT` / `KEYWORDS_TREND`：

```python
KEYWORDS_CORE = ["珍珠", "珠宝 珍珠", "珍珠项链", "珍珠首饰"]
KEYWORDS_EVENT = ["珍珠 新品发布", "珠宝展 珍珠", ...]
KEYWORDS_TREND = ["珍珠 时尚", "淡水珍珠", "Akoya 珍珠", ...]
```

### 修改时效窗口

编辑 `pearl_news.py` 顶部的常量：

```python
HOT_WINDOW_HOURS = 48          # 热点模式时间窗
FALLBACK_WINDOW_HOURS = 24 * 7  # 降级模式时间窗
HOT_MIN_COUNT = 3              # 触发正常模式的最少条数
NORMAL_MAX_COUNT = 8           # 正常模式最多推送条数
FALLBACK_MAX_COUNT = 4         # 降级模式最多推送条数
```

### 修改推送时间

编辑 `.github/workflows/daily_news.yml` 中的 cron 表达式：

```yaml
schedule:
  - cron: '0 23 * * *'   # UTC 23:00 = 北京 07:00
  - cron: '0 0 * * *'    # UTC 00:00 = 北京 08:00
```

常见时间对照（北京时间 = UTC + 8）：
- 早上 7:00 → `cron: '0 23 * * *'`（前一天 UTC 23:00）
- 中午 12:00 → `cron: '0 4 * * *'`
- 晚上 20:00 → `cron: '0 12 * * *'`

## 项目结构

```
pearl-news-bot/
├── .github/
│   └── workflows/
│       └── daily_news.yml   # GitHub Actions 双触发定时任务
├── pearl_news.py            # 主程序：多源抓取 + 主题分类 + 日报构建 + 钉钉推送
├── requirements.txt         # Python 依赖（requests/bs4/lxml/pytz）
├── .gitignore
└── README.md                # 本文件
```

## 常见问题

**Q: 钉钉收不到消息？**
- 检查 GitHub Secrets 中 `DINGTALK_WEBHOOK` 是否正确设置
- 检查钉钉机器人的安全关键词是否包含「珍珠」
- 查看 Actions 运行日志：若主流程异常会自动发告警到钉钉

**Q: 早上没收到推送？**
- GitHub Actions cron 高峰期可能排队延迟，已通过 07:00 + 08:00 双触发兜底
- 若两次都失败，查看 Actions 日志的 `send_dingtalk` 错误码
- 机器人消息频率限制（1分钟20条），日志会显示频率限制告警

**Q: 抓取不到内容？**
- 查看日志中各数据源的抓取条数：中宝协 / Bing / 今日热榜 / 搜狗
- Bing News 反爬较轻，通常稳定；中宝协官网偶尔慢
- 完全无内容时会推送"今日暂无资讯"提示，便于区分故障

**Q: 链接打不开？**
- v2 已修复：跟随重定向拿真实 URL + HEAD 校验
- 若仍有失效链接，查看日志中 `validate_url` 过滤记录

**Q: 如何修改降级策略？**
- 调整 `HOT_MIN_COUNT`（触发降级阈值）和 `FALLBACK_MAX_COUNT`（降级条数）
- 完全无热点时是否推送提示，修改 `main()` 中的 empty 分支逻辑

## License

MIT
