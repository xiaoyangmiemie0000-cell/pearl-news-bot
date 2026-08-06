# 💎 珍珠珠宝新闻自动推送机器人

每天自动从多个渠道抓取珍珠/珠宝相关新闻，通过**钉钉机器人**推送到手机。

## 功能特性

- **多渠道聚合**：百度新闻、搜狗新闻、中国珠宝网、微博、京东
- **关键词覆盖**：珍珠新品、代言人、品牌发布、拍卖、时尚趋势等
- **定时推送**：每天早上 8:00（北京时间）自动运行
- **钉钉通知**：Markdown 格式，按来源分组，附带原文链接
- **GitHub Actions**：免费云端运行，无需本地服务器

## 数据源

| 分类 | 来源 | 说明 |
|------|------|------|
| 综合新闻 | 百度新闻、搜狗新闻 | 主流媒体珍珠珠宝资讯 |
| 行业网站 | 中国珠宝网 | 垂直行业门户 |
| 社交媒体 | 微博 | 热门话题与讨论 |
| 电商平台 | 京东 | 珍珠新品与价格 |

## 快速开始

### 1. Fork 或克隆此仓库

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

编辑 `pearl_news.py` 中的 `KEYWORDS` 列表：

```python
KEYWORDS = [
    "珍珠 新品",
    "珍珠 代言人",
    # 添加你自己的关键词...
]
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

### 添加/删除数据源

在 `pearl_news.py` 中修改对应的 `SOURCES_*` 列表即可。

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
- 部分网站可能有反爬机制，可尝试调整请求间隔
- 查看 Actions 日志中的具体错误信息

**Q: 如何修改推送频率？**
- 修改 `daily_news.yml` 中的 cron 表达式，或添加多个定时规则

## License

MIT
