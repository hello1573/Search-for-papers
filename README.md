# 稀疏地形重建文章日报

这个仓库每天北京时间 10:00 运行一次，检索 OpenAlex 中与以下主题相关的文章：

- 稀疏地形重建
- 稀疏 DEM 重建与修复
- 数字高程模型补全
- 地形表面重建与插值
- 点云高程补全
- 遥感 DEM 缺失区域修复

脚本会筛选最多 8 篇高相关结果，并发布到仓库中的固定日报 Issue。每次发布都会 @ 仓库所有者，因此 GitHub 会按账号的通知设置发送邮件。GitHub Actions 的定时任务使用 UTC 时间，因此配置为每天 `02:00 UTC`。

## 配置 GitHub Secrets

在仓库的 **Settings -> Secrets and variables -> Actions** 中可选配置：

1. `OPENALEX_MAILTO`：用于 OpenAlex 礼貌池的邮箱，可选。

日报正文通过 GitHub 通知邮件发送，不需要 PushPlus Token 或 SMTP 密码。

## 手动测试

打开仓库的 **Actions -> Daily sparse terrain paper digest -> Run workflow**，可以立即运行一次。运行成功后，日报会出现在固定的 `[论文日报] 稀疏地形重建文章日报` Issue 中，并触发 GitHub 邮件通知。

本地运行：

```powershell
python -m pip install -r requirements.txt
python paper_digest.py --output digest.md
```
