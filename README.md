# MathorCup 赛道 B：处理代码与分析说明

本目录只保留数据处理、核查和第一问分析所用的 Python 脚本，以及相应的 Markdown 说明与审查报告。原始比赛数据、网站下载包、CSV/数据库结果、模型依赖、PDF 和 LaTeX 编译文件不在本目录中。

## 内容

| 目录 | 内容 |
|---|---|
| `第一问/` | 基础逐小时数据整理脚本和使用说明 |
| `数据分析/` | 八类附件审计脚本与分析报告 |
| `第一问重做_20261025/` | 第一问关联排序重算脚本与结果解读 |
| `数据预处理_流程图_20261025/` | 分类、物理特征、缺失、IQR、标准化的处理脚本与结果说明 |
| `成果审查/` | 两个既有成果包审查、FLUX 来源核查脚本与报告 |
| `第一问论文稿_20261025/` | 第一问图形生成脚本 |

## 复现前提

脚本按原工作区的相对目录寻找比赛附件与核查结果。此仓库不提供原始数据；运行前需自行取得相应附件，并将其放回脚本预期的位置。部分脚本依赖 `pandas`、`numpy`、`scipy`、`scikit-learn`、`matplotlib`、`rasterio` 和 `h5py`。具体数据来源、缺测与 QC 口径见各目录中的 Markdown 文件。

第一问的五项排序来自单次事件的描述性对照，不能当作触发因果或可推广的预报准确率。2024—2026 年 FLUX 仅见于本地比赛附件，且没有官方 QC 列。

## 推送到自己的 GitHub 仓库

在 GitHub 网页创建空仓库后，于本目录运行：

```powershell
git init -b main
git add .
git status --short
git commit -m "Add processing code and analysis notes"
git remote add origin 'https://github.com/你的用户名/你的仓库名.git'
git push -u origin main
```

执行 `git commit` 前检查 `git status --short`，确认没有意外文件。远程仓库地址应替换为 GitHub 新仓库页面给出的地址。
