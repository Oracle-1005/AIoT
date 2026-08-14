# AIoT 智能指挥演奏系统 · Smart Conducting Performance System

> 用双手指挥一支虚拟乐队：手势识别 → 实时遥控 Sonic Pi 多轨混音 → LED 波形可视化
> SWS3025 Group P01 课程项目

徒手在空中比划，就能控制一首歌的播放、音量、BPM、四个声部的开关与音乐风格切换——
无需任何穿戴式操控设备以外的道具，**一块摄像头 + 两块 micro:bit 腕带**就是全部输入。

## ✨ 演示效果（Features）

- 🖐 **徒手指挥**：左拳停 / 右拳开，推掌调音量，推拳调 BPM，双拳比高低切风格
- 🎚 **四声部空中混音台**：双掌悬停在画面中四个高度分区，静止 1 秒即可点亮/关闭
  melody / harmony / bass / drums 四条音轨
- 🎹 **Sonic Pi 实时发声**：全部命令经 OSC 直达 Sonic Pi 现场合成，不是放录音——
  BPM、音量、声部、风格全部实时生效
- 📟 **双 16×32 LED 点阵**：Raspberry Pi 5 GPIO 直驱，实时音乐波形
- ⌚ **micro:bit 腕带锚点门控**：BLE 加速度数据作为"在场证明"，未佩戴者无法误触发
- 📷 **Pi Camera 端侧推理**：MediaPipe 骨架在 Pi 上完成并烧制到 MJPEG 预览流，
  PC 端只做高层手势状态机判定

## 🖐 坐标手势体系

| 手势 | 动作 |
|------|------|
| 右拳（先张掌再握拳） | ▶ 开始播放 |
| 左拳 | ⏸ 停止 |
| 左掌上推 / 右掌下推 | 音量 ± |
| 左拳上推 / 右拳下推 | BPM ±8 |
| 双拳 左高右低 / 右高左低 | 上一 / 下一风格（acoustic_pop → tropical_house → festival_edm） |
| 双掌悬停于高度分区 | 开启对应声部（上→下：melody → harmony → bass → drums） |
| 双拳悬停于高度分区 | 关闭对应声部 |

可靠性设计：握拳必须"先出掌再握"（`seen_palm` 防误触）、帧数持续判定（HOLD_FRAMES）、
分区死区防抖动、micro:bit 锚点活性门控、单手纪律防双手串扰。

## 🏗 系统架构

```
 micro:bit ×2                 Pi 5 (Camera + LED)                PC
 ┌──────────┐   BLE    ┌──────────────────────┐   TCP :9000   ┌────────────────────┐
 │ 加速度计  │ ──────► │ BLE 网关 → fusion 服务 │ ───────────► │ Flask 后端          │
 └──────────┘         │ MediaPipe 手部骨架      │  fused_frame │  坐标手势状态机       │
                      │ 16Hz 融合帧             │              │  SQLite / OSC 客户端 │
                      └──────────┬───────────┘              └──────┬─────────┬─────┘
                                 │ MJPEG :8790                      │ OSC     │ HTTP 轮询
                                 ▼                                 ▼         ▼
                          前端摄像头画面(带分区 overlay)      Sonic Pi      React 前端
                          (React Dashboard)                多轨实时合成    Dashboard
```

- **Pi 侧**：摄像头 → MediaPipe hand landmarks → 与 micro:bit BLE 数据融合为
  `fused_frame`（JSON Lines @16Hz）→ TCP 推送 PC；LED 点阵由 led_consumer 驱动
- **PC 后端**：坐标手势识别（9 种动作状态机）→ OSC 命令通道（带 command_id /
  ack / 重试 / 超时）→ Sonic Pi；Flask API 供前端轮询
- **Sonic Pi**：单机安全模式加载单曲（Shape of You，由 MIDI 自动生成 6600+ 行
  演奏代码），`/conductor/{transport,volume,bpm,layer,style}` OSC 接收器 +
  `/music/{beat,state,layers,ack}` 反馈回路
- **前端**：React + Vite，摄像头画面叠加四声部分区线与骨架，声部 ON/OFF 实时芯片，
  命令通道健康指示灯（Command Channel Dead 红灯告警）

## 🛠 技术栈

| 层 | 技术 |
|----|------|
| 视觉 | MediaPipe Hand Landmarker（Pi 5 端侧） |
| 手势判定 | 自研坐标手势状态机（Python，16 项单元测试覆盖） |
| 音乐引擎 | Sonic Pi（Ruby/OSC，实时合成，MIDI→Sonic Pi 代码生成器） |
| 后端 | Flask + SQLite + python-osc |
| 前端 | React + Vite |
| 硬件 | Raspberry Pi 5、Pi Camera、micro:bit ×2（BLE）、双 16×32 LED 点阵（GPIO 直驱） |
| 机器学习 | Random Forest 手势分类管线（`model/`，辅助路径） |

## 📁 项目结构

```
AIoT/
├── model/       # MediaPipe + Random Forest 推理 pipeline
├── backend/     # Flask API / 坐标手势识别器 / OSC 命令通道 / Pi 网关
├── frontend/    # React + Vite Dashboard
├── music/       # Sonic Pi 演奏文件、MIDI 代码生成器、loader
├── pi5/         # Pi 端服务：BLE 接收 / fusion / LED 驱动 / 部署脚本
├── hardware/    # micro:bit 固件与硬件资料
├── data/        # 采集数据与数据库
└── docs/        # 技术规格、接口协议、开发指南
```

## 📄 文档

| 文档 | 内容 |
|------|------|
| [docs/TECHNICAL_SPEC.md](docs/TECHNICAL_SPEC.md) | 硬件参数、网络拓扑、技术栈 |
| [docs/INTERFACE_CONTRACT.md](docs/INTERFACE_CONTRACT.md) | 模块间数据格式与通信协议 |
| [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) | 各端环境搭建指南 |

## 👥 团队

| 角色 | 成员 | 职责 |
|------|------|------|
| 组长 + 模型 | 王祎哲 (t0939395) | MediaPipe + Random Forest 推理 pipeline |
| 前端 | 王玺达 (t0939390) | React Dashboard + 可视化 |
| 后端 | 罗子超 (t0939291) | Flask + SQLite + OSC 命令通道 |
| 硬件 | 王俊智 (t0939382) | micro:bit BLE 固件 + 腕带 + 传感器 |
| 硬件 | 王清源 (t0939384) | Pi 5 + LED Matrix (GPIO 直驱) + Pi Camera |
