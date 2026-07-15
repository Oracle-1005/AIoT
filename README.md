# AIoT Smart Conducting Performance System
# SWS3025 Group P01

## 快速链接

| 文档 | 用途 |
|------|------|
| [技术规格](docs/TECHNICAL_SPEC.md) | 硬件参数、网络拓扑、技术栈 |
| [接口协议](docs/INTERFACE_CONTRACT.md) | 各模块间数据格式和通信协议 |
| [开发指南](docs/DEVELOPMENT_GUIDE.md) | 各端环境搭建与第一周任务 |

## 团队

| 角色 | 成员 | 职责 |
|------|------|------|
| 组长 + 模型 | 王祎哲 (t0939395) | MediaPipe + Random Forest 推理 pipeline |
| 前端 | 王玺达 (t0939390) | HTML + Chart.js Dashboard + Web Audio API |
| 后端 | 罗子超 (t0939291) | Flask + SQLite + MQTT Client API |
| 硬件 | 王俊智 (t0939382) | Micro:bit BLE 固件 + 腕带 + 传感器 |
| 硬件 | 王清源 (t0939384) | Pi 5 + LED Matrix (GPIO 直驱) + Pi Camera |

## 项目结构

```
AIoT/
├── model/       # 模型（MediaPipe + Random Forest）
├── backend/     # Flask + SQLite + MQTT
├── frontend/    # HTML + Chart.js Dashboard
├── hardware/    # Micro:bit 固件 / Pi 5 配置和 LED 驱动脚本
├── data/        # 采集数据和数据库
└── docs/        # 技术文档
```

## 关键日期

| 日期 | 事项 |
|------|------|
| 7/15 | 领取设备 ✅ |
| 7/16 | 项目咨询 |
| 7/21 | 第一周里程碑检查 |
| 7/29 | 最终交付 |
