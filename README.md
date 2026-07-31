# JaneHu 工作台（云端版）

手机工作台：**待办 / 记账 / 学习 / 新闻 / 专注** 五合一。

## 手机访问地址

`https://<你的GitHub用户名>.github.io/workbench/`

## 工作原理

- **页面**：`index.html` 部署在 GitHub Pages，公网永久可访问（电脑关机也不影响打开）
- **数据**：`news.json`（央视/人民网/新华网头条+简介）与 `study.json`（YouTube/抖音/小红书 AI 学习视频+中文简介）由 GitHub Actions 每天 **北京时间 08:00 与 14:00** 自动抓取并发布，完全在云端运行，与你的电脑无关
- **个人数据**：待办/记账/专注保存在手机浏览器本地（localStorage），不经过云端

## 每日抓取

`news_fetch.py` + `study_fetch.py` 在 GitHub 云端（Linux）运行：

| 文件 | 内容 |
|---|---|
| news.json | 国内头条·央视、国际头条·人民网、国内要闻·新华网（各带简要内容） |
| study.json | YouTube AI 学习（7 个频道，中文简介）、抖音 AI 热点、小红书 AI 学习 |

## 手动更新

仓库 Actions 页 → `daily-fetch` → `Run workflow` 可随时手动触发抓取。

## 本地开发（可选）

电脑上也可直接运行脚本（Python 3.11+，无第三方依赖）：

```bash
python news_fetch.py    # 生成 news.json
python study_fetch.py   # 生成 study.json
```

本地局域网访问（电脑开机时）：`python -m http.server 8898 --bind 0.0.0.0`
