# 自动更新玩机文件与 Modules

## 项目简介

这是一个自动同步和更新玩机文件的 GitHub 项目，例如 ZygiskNext、TrickyStore 等常用工具和模块。

通过 GitHub Actions，它会每天自动检查上游项目的 Release 更新，并下载最新文件到本仓库中，实现集中管理和自动化同步。

## 项目意义

诚然，这些文件都可以从各自的官网直接下载。但玩机文件通常数量较多，且官网链接不易记忆和追踪。

本项目的优势在于：
- **集中管理**：将所有玩机文件聚合到一个仓库，避免到处寻找官网链接。
- **自动更新**：每天检测上游更新，有新版本时自动拉取并替换旧文件。
- **历史追溯**：通过 Git 提交记录，可以查看每次更新的变更历史。
- **简单下载**：无需手动操作，一键访问所有最新文件。

## 如何使用

- **下载文件**：直接从本项目的 [downloads 文件夹](https://github.com/666mingqing6/auto-sync-releases/tree/main/downloads) 中获取所需文件。

## 支持的项目

当前支持的项目包括（详见 `projects.yaml` 配置）：
- ZygiskNext
- TrickyStore
- yurikey
- PlayIntegrityFork
- HMA-OSS
- fuckluna
- WebUI-X-Portable
- ZN-AuditPatch
- Magisk_AsoulOpt
- Uperf-Game-Turbo

欢迎 Star 或 Fork 本仓库，如果有问题，随时反馈！
