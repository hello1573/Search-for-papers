# 稀疏地形重建文章日报

这个仓库每天北京时间 10:00 运行一次，检索 OpenAlex 中与以下主题相关的文章：

- 稀疏地形重建
- 稀疏 DEM 重建与修复
- 数字高程模型补全
- 地形表面重建与插值
- 点云高程补全
- 遥感 DEM 缺失区域修复

脚本会筛选最多 8 篇高相关结果，只保留最近两年发表的文章，并优先推荐最新发表的结果。论文必须同时涉及地形、DEM、高程、点云等核心对象，以及重建、补全、修复或插值任务。已发送的论文会记录在 `seen_papers.json` 中，后续运行不会重复推送。日报发布到仓库中的固定 Issue，每次发布都会 @ 仓库所有者，因此 GitHub 会按账号的通知设置发送邮件。GitHub Actions 的定时任务使用 UTC 时间，因此配置为每天 `02:00 UTC`。

## 已有文献排除

`known_papers.json` 保存从《论文梳理_地形恢复.docx》提取的文献：85 条文献条目合并重复后为 83 篇，包含 100 个标题及标题别名。没有上传原文档或研究笔记。无 DOI 的条目通过标题匹配，统一大小写、空格、标点、连字符和全角字符，并移除文档中附加的期刊名。标题的完整翻译或大幅改写不能仅靠此匹配识别；这类条目可补充 DOI 或原文标题作为别名。

每次检索同时排除 `known_papers.json` 中的已有文献和 `seen_papers.json` 中的推送记录，再按发表日期由新到旧选择最多 8 篇。同一期也按 DOI、来源链接和标题去重。没有新论文时不发送通知。

可在手动运行时勾选 `dry_run`，仅生成预览和运行验证，不发布 Issue 通知或更新推送记录。

## 配置 GitHub Secrets

在仓库的 **Settings -> Secrets and variables -> Actions** 中可选配置：

1. `OPENALEX_MAILTO`：用于 OpenAlex 礼貌池的邮箱，可选。

日报正文通过 GitHub 通知邮件发送，不需要 PushPlus Token 或 SMTP 密码。

## 手动测试

打开仓库的 **Actions -> Daily sparse terrain paper digest -> Run workflow**，可以立即运行一次。运行成功后，日报会出现在固定的 `[论文日报] 稀疏地形重建文章日报` Issue 中，并触发 GitHub 邮件通知。

本地运行：

```powershell
python -m pip install -r requirements.txt
python paper_digest.py --output digest.md --state seen_papers.json
```
