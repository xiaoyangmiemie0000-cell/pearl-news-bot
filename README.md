# 💎 珍珠珠宝新闻自动推送机器人

每天自动从百度资讯、搜狗新闻等渠道抓取珍珠/珠宝相关新闻，通过**钉钉机器人**推送到手机。

## 功能特性

- **多渠道聚合**：百度资讯、搜狗新闻
- **关键词覆盖**：珍珠新品、代言人、品牌发布、拍卖、时尚趋势等 20+ 组关键词
- **定时推送**：每天早上 8:00（北京时间）自动运行
- **钉钉通知**：Markdown 格式，按来源分组，附带原文链接
- **智能过滤**：自动排除百科、医疗、电商等非新闻内容
- **GitHub Actions**：免费云端运行，无需本地服务器

## 数据源

| 数据源 | 说明 | 状态 |
|--------|------|------|
| 百度资讯 | 百度新闻搜索，覆盖新浪、网易、搜狐等主流媒体 | ✅ 可用 |
| 搜狗新闻 | 搜狗新闻搜索，作为补充数据源 | ✅ 可用（偶有反爬） |

## 快速开始

### 1. Fork 或克隆此仓库

```bash
git clone https://github.com/chinalei0428-lang/pearl-news-bot.git
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

配置完成后，GitHub Actions 会在每天 UTC 00:00（北京时间 08:00）自动运行，将新闻推送到你的钉钉群。

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 直接运行（不推送，仅打印到控制台）
python pearl_news.py

# 带钉钉推送运行
set DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=你的token
python pearl_news.py
```

## 自定义配置

### 修改关键词

编辑 `pearl_news.py` 中的关键词列表：

```python
KEYWORDS_CORE = ["珍珠", "珠宝 珍珠", "珍珠项链", "珍珠首饰"]
KEYWORDS_BRAND = ["御木本 珍珠", "Mikimoto", "京润珍珠", "周大福 珍珠"]
KEYWORDS_EVENT = ["珍珠 新品发布", "珍珠 代言人", "珠宝展 珍珠"]
KEYWORDS_TREND = ["珍珠 时尚", "淡水珍珠", "海水珍珠", "巴洛克珍珠"]
```

### 修改推送时间

编辑 `.github/workflows/daily_news.yml` 中的 cron 表达式：

```yaml
schedule:
  # 格式：分 时 日 月 周（UTC 时间）
  # 北京时间 = UTC + 8
  - cron: '0 0 * * *'  # 当前：北京时间 08:00
```

常见时间对照：
- 早上 7:00 → `cron: '0 23 * * *'`（前一天 UTC 23:00）
- 中午 12:00 → `cron: '0 4 * * *'`
- 晚上 20:00 → `cron: '0 12 * * *'`

## 项目结构

```
pearl-news-bot/
├── .github/
│   └── workflows/
│       └── daily_news.yml   # GitHub Actions 定时任务
├── pearl_news.py            # 主程序：新闻抓取 + 钉钉推送
├── requirements.txt         # Python 依赖
├── .gitignore
└── README.md                # 本文件
```

## 常见问题

**Q: 钉钉收不到消息？**
- 检查 GitHub Secrets 中 `DINGTALK_WEBHOOK` 是否正确设置
- 检查钉钉机器人的安全关键词是否包含「珍珠」
- 查看 Actions 运行日志排查错误

**Q: 抓取不到内容？**
- 百度/搜狗可能有反爬机制，程序会自动重试
- GitHub Actions 运行在美国服务器，访问国内网站可能不稳定
- 查看 Actions 日志中的具体错误信息

**Q: 如何修改推送频率？**
- 修改 `daily_news.yml` 中的 cron 表达式，或添加多个定时规则

## License

MIT
