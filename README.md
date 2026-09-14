# 稀疏地形重建文章日报

这个仓库每天北京时间 10:00 运行一次，检索 OpenAlex 中与以下主题相关的文章：

- 稀疏地形重建
- 稀疏 DEM 重建与修复
- 数字高程模型补全
- 地形表面重建与插值
- 点云高程补全
- 遥感 DEM 缺失区域修复

脚本会筛选最多 8 篇高相关结果，并通过 PushPlus 微信公众号推送。GitHub Actions 的定时任务使用 UTC 时间，因此配置为每天 `02:00 UTC`。

## 配置 GitHub Secrets

在仓库的 **Settings -> Secrets and variables -> Actions** 中新增：

1. `PUSHPLUS_TOKEN`：PushPlus 公众号提供的 Token，必填。
2. `OPENALEX_MAILTO`：用于 OpenAlex 礼貌池的邮箱，可选。

不要把 Token 写入代码、README 或提交记录。

## 手动测试

打开仓库的 **Actions -> Daily sparse terrain paper digest -> Run workflow**，可以立即运行一次。首次测试前必须先配置 `PUSHPLUS_TOKEN`。

本地运行：

```powershell
python -m pip install -r requirements.txt
$env:PUSHPLUS_TOKEN = "你的Token"
python paper_digest.py
```
