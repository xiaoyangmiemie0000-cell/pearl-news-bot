#  珍珠珠宝新闻自动推送机器人

每天自动从搜狗新闻、百度资讯等渠道抓取珍珠/珠宝相关新闻，通过 **LLM 智能摘要**按「时间 / 地点 / 人物 / 事件 / 影响」格式归纳，再通过**钉钉机器人**推送到手机。

## 功能特性

- **多渠道聚合**：搜狗新闻、百度资讯
- **关键词覆盖**：珍珠新品、代言人、品牌发布、拍卖、时尚趋势等 20+ 组关键词
- **LLM 智能摘要**：AI 自动将每条新闻归纳为「时间 / 地点 / 人物 / 事件 / 影响」结构化格式
- **定时推送**：每天早上 8:00（北京时间）自动运行
- **钉钉通知**：Markdown 格式，附带原文链接
- **智能过滤**：自动排除百科、医疗、电商等非新闻内容
- **GitHub Actions**：免费云端运行，无需本地服务器

## 数据源

| 数据源 | 说明 | 状态 |
|--------|------|------|
| 搜狗新闻 | 搜狗新闻搜索，主力数据源 | ✅ 可用 |
| 百度资讯 | 百度新闻搜索，补充数据源 | ✅ 可用 |

## 快速开始

### 1. Fork 或克隆此仓库

```bash
git clone https://github.com/xiaoyangmiemie0000-cell/pearl-news-bot.git
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
3. 点击 **New repository secret**，依次添加以下 Secret：

| Secret 名称 | 必填 | 说明 |
|-------------|------|------|
| `DINGTALK_WEBHOOK` | ✅ | 钉钉机器人 Webhook 地址 |
| `LLM_API_KEY` | 推荐 | LLM API 密钥（不填则降级为原始标题模式） |
| `LLM_API_BASE` | 可选 | LLM API 地址，默认 `https://api.deepseek.com` |
| `LLM_MODEL` | 可选 | 模型名称，默认 `deepseek-chat` |

4. 点击 **Add secret** 保存

### 4. 手动测试

1. 进入仓库的 **Actions** 页面
2. 选择左侧「珍珠珠宝新闻日报」
3. 点击 **Run workflow** 手动触发一次
4. 检查钉钉群是否收到消息

### 5. 自动运行

配置完成后，GitHub Actions 会在每天 UTC 00:00（北京时间 08:00）自动运行，将新闻推送到你的钉钉群。

## LLM 智能摘要配置

### 支持的 LLM 服务商

本项目支持所有 **OpenAI 兼容接口**的 LLM 服务商，推荐以下国内服务：

| 服务商 | API Base | 推荐模型 | 价格 |
|--------|----------|----------|------|
| **DeepSeek** | `https://api.deepseek.com` | `deepseek-chat` | 极低（推荐） |
| **通义千问** | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | 低 |
| **智谱 AI** | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | 免费额度 |
| **月之暗面** | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | 低 |
| **OpenAI** | `https://api.openai.com` | `gpt-4o-mini` | 中 |

### 以 DeepSeek 为例（推荐）

1. 访问 https://platform.deepseek.com/ 注册账号
2. 在「API Keys」页面创建一个新的 API Key
3. 充值少量金额（1 元可用很久）
4. 在 GitHub Secrets 中添加：
   - `LLM_API_KEY` = 你的 DeepSeek API Key
   - `LLM_API_BASE` = `https://api.deepseek.com`（默认值，可不填）
   - `LLM_MODEL` = `deepseek-chat`（默认值，可不填）

### 摘要效果示例

开启 LLM 后，每条新闻会被归纳为如下格式：

```
📅 时间：2026年8月6日
📍 地点：浙江诸暨
👤 人物/机构：阮仕珍珠、代言人刘亦菲
📝 事件：阮仕珍珠发布2026秋季高定系列，由刘亦菲担任品牌代言人出席发布会
💡 影响：标志着国产珍珠品牌向高端化转型，有望提升消费者对国产珍珠的认知度和购买意愿
 来源：[原文链接]
```

> 未配置 LLM API Key 时，程序会自动降级为原始标题 + 摘要模式，不影响基本功能。

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 直接运行（不推送，仅打印到控制台）
python pearl_news.py

# 带钉钉推送运行
set DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=你的token
set LLM_API_KEY=sk-你的API密钥
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
│   ── workflows/
│       └── daily_news.yml   # GitHub Actions 定时任务
├── pearl_news.py            # 主程序：新闻抓取 + LLM摘要 + 钉钉推送
├── requirements.txt         # Python 依赖
├── .gitignore
└── README.md                # 本文件
```

## 常见问题

**Q: 钉钉收不到消息？**
- 检查 GitHub Secrets 中 `DINGTALK_WEBHOOK` 是否正确设置
- 检查钉钉机器人的安全关键词是否包含「珍珠」
- 查看 Actions 运行日志排查错误

**Q: LLM 摘要没有生效？**
- 检查是否配置了 `LLM_API_KEY`
- 查看 Actions 日志中是否有 "未配置 LLM_API_KEY" 的提示
- 未配置时会自动降级为原始标题模式，不影响基本功能

**Q: 抓取不到内容？**
- 搜狗/百度可能有反爬机制，程序会自动重试
- GitHub Actions 运行在美国服务器，访问国内网站可能不稳定
- 查看 Actions 日志中的具体错误信息

**Q: 如何修改推送频率？**
- 修改 `daily_news.yml` 中的 cron 表达式，或添加多个定时规则

## License

MIT
