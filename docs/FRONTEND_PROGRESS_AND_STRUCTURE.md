# 前端进度与结构说明

**负责人**: 前端
**日期**: 2026-07-23
**前端状态基准**: `7f68310`
**前端目录**: `frontend/`

本文档用于记录当前前端负责部分的完成进度、项目结构、后端对接方式和后续需要配合的事项，方便组内同步和路演前交接。

---

## 1. 当前进度

前端已经完成一个用于路演展示的 React 大屏应用，核心展示链路为：

```text
Camera + Micro:bit + ESP32/Pi 网关 + Raspberry Pi 5
        -> 本地 AI / 手势事件识别
        -> PC 后端
        -> Sonic Pi 音乐控制 + 数据库记录
        -> 前端路演展示界面
```

目前前端支持两种运行状态：

- **真实后端模式**: 通过 Flask REST API 轮询实时数据。
- **Mock 兜底模式**: 后端未启动时自动展示模拟数据，保证路演页面可以正常打开和演示。

路演界面中的主要展示文字已经改为英文，便于全英文汇报。中文只保留在素材占位说明、内部交接备注等地方。

---

## 2. 已完成页面

| 模块 | 状态 | 作用 |
|---|---:|---|
| Hero 首页 | 已完成 | 展示项目概念，并提供进入路演模式的入口。 |
| Live Conducting Stage | 已完成 | 主演示页面，集中展示摄像头、AI、Micro:bit 和音乐控制。 |
| Camera / Gesture Panel | 已完成 | 展示手部检测、追踪状态、FPS、延迟、轨迹和摄像头素材占位。 |
| AI Prediction Card | 已完成 | 展示当前手势、置信度、Top-3 预测结果和支持的手势类别。 |
| 双 Micro:bit 传感器卡片 | 已完成 | 展示左右手设备状态和三轴加速度数据。 |
| Music Control Center | 已完成 | 展示 Sonic Pi 曲目、BPM、音量、能量、密度、段落、Bar/Beat 和播放控制。 |
| AI Decision Flow | 已完成 | 展示 Camera + IMU 到特征、手势事件、音乐映射和数据库记录的流程。 |
| Proof Points | 已完成 | 用更自然的方式回答技术验证点，避免直接写“导师最关心的问题”。 |
| Historical Analytics | 已完成 | 展示模拟历史分析、手势分布、置信度/延迟趋势和事件记录。 |
| Architecture View | 已完成 | 展示感知层、边缘/网络层、AI 层、音乐输出层和数据层。 |
| Calibration & Training | UI 已完成 | 展示校准清单和手势采集入口，真实录制接口暂未接入。 |
| About | 已完成 | 展示项目问题、方案、创新点和应用场景。 |
| 全屏 Presentation Mode | 已完成 | 四页式路演模式，包含实时状态横条和不同展示视图。 |

---

## 3. 前端目录结构

```text
frontend/
├── index.html
├── package.json
├── package-lock.json
├── vite.config.js
├── tailwind.config.js
├── postcss.config.js
├── README.md
├── public/
│   ├── favicon.svg
│   └── media/
│       └── README.md
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── index.css
    ├── data/
    │   └── conductorData.js
    └── hooks/
        └── useConductorFeed.js
```

关键文件说明：

| 文件 | 作用 |
|---|---|
| `src/App.jsx` | 前端主界面，包含所有页面模块、音乐控制面板、路演模式和整体布局。 |
| `src/hooks/useConductorFeed.js` | 数据适配层，负责 REST 轮询、可选 WebSocket、Mock 兜底和 Sonic Pi 控制请求。 |
| `src/data/conductorData.js` | 模拟数据、手势目录、图表数据、验证卡片、素材占位和兜底数据生成。 |
| `src/index.css` | 全局样式、Tailwind 扩展样式、暗色科技风面板和按钮样式。 |
| `public/media/README.md` | 说明真实视频和图片应该放在哪里。 |
| `frontend/README.md` | 前端启动方式、后端接口、素材替换和运行说明。 |

---

## 4. 当前后端对接方式

前端不直接连接 Raspberry Pi、ESP32、Micro:bit 或 Sonic Pi。
前端只和 PC 端 Flask 后端通信。

默认后端地址：

```text
http://localhost:5000
```

可通过前端环境变量配置：

```text
VITE_BACKEND_BASE_URL=http://localhost:5000
```

当前前端轮询的 REST 接口：

```text
GET /api/status
GET /api/gesture/current
GET /api/sensors/live
GET /api/music/state
GET /api/pi/status
```

音乐播放按钮使用的 Sonic Pi 控制接口：

```text
POST /api/sonic-pi/transport
Body: { "action": "start" | "pause" | "reset" | "cutoff" }
```

预留的 WebSocket 配置：

```text
VITE_CONDUCTOR_WS_URL=ws://localhost:8000/ws/frontend
```

当前 REST 轮询间隔：

```text
250 ms
```

---

## 5. 前端数据适配逻辑

前端数据适配文件：

```text
frontend/src/hooks/useConductorFeed.js
```

这个文件会把后端返回的数据统一整理成前端展示用的 `frame`，页面上的所有模块都从这个 `frame` 读取数据。

当前支持的实时字段：

| 展示区域 | 后端数据来源 |
|---|---|
| 摄像头连接 / 手部检测 | `/api/status`、`/api/sensors/live` |
| AI 手势和置信度 | `/api/gesture/current`、`/api/pi/status.runtime.last_control_event` |
| Top-3 预测结果 | `/api/gesture/current.all_probs` |
| 左右 Micro:bit 加速度 | `/api/sensors/live.microbit_left/right` |
| Raspberry Pi 网关状态 | `/api/status.pi_gateway`、`/api/pi/status.gateway` |
| Pi 消息计数 | `/api/pi/status.runtime.message_counts` |
| Sonic Pi 连接 / BPM / Bar / Beat | `/api/music/state` |
| Sonic Pi 播放/暂停 | `POST /api/sonic-pi/transport` |

Micro:bit 加速度当前兼容多种格式：

```text
acc_x / acc_y / acc_z
ax_mg / ay_mg / az_mg
raw_interpolated.acceleration_mg
instant_features.acceleration_g
```

因此即使硬件和后端字段还在调整，只要后端仍返回以上任意一种格式，前端都能正常显示加速度。

---

## 6. 当前硬件链路假设

最新仓库中已经新增 Pi 侧融合流水线：

```text
hardware/fusion_pipeline/
```

当前预期实时链路：

```text
Micro:bit L/R
  -> ESP32 BLE-to-Wi-Fi 网关
  -> Raspberry Pi fusion pipeline
  -> TCP JSON Lines 发送到 PC 后端 9000 端口
  -> Flask REST API
  -> React 前端
```

前端边界：

- 前端继续读取 PC 后端 API。
- 前端不直接读取 ESP32 UDP 包，也不直接读取 Pi 摄像头原始帧。
- 如果硬件内部链路调整，但后端 REST API 不变，前端通常不需要修改。
- 如果后端接口字段或接口路径变化，前端再做小范围适配。

---

## 7. 真实素材占位

前端已经为真实路演素材预留位置。最终视频和图片放到：

```text
frontend/public/media/
```

建议文件名：

| 文件 | 用途 |
|---|---|
| `roadshow-demo.mp4` | 首页 Hero 路演视频 |
| `live-camera-demo.mp4` | 摄像头识别 / 手部关键点画面 |
| `microbit-wrist.jpg` | Micro:bit 佩戴照片 |
| `team-roadshow.jpg` | 团队、设备或路演现场照片 |

建议录制素材：

- 一段 20 到 40 秒的横屏视频，展示同学双手指挥，同时前端音乐参数发生变化。
- 一段带手部关键点、骨架线或识别标签的摄像头识别画面。
- 左右手佩戴 Micro:bit 的清晰近景照片。
- 一张完整设备或小组调试/路演现场照片。

注意：当前前端已经预留摄像头素材区域，但还没有接入真正的 Pi Camera 实时视频流。
如果最终路演需要在前端显示真实实时摄像头画面，需要后端或 Pi 侧提供稳定的视频流地址，例如 MJPEG、WebRTC 或定时图片帧。

---

## 8. 本地启动方式

```bash
cd frontend
npm install
npm run dev
```

然后打开 Vite 终端输出的本地地址。

如果要连接真实后端：

```text
VITE_BACKEND_BASE_URL=http://localhost:5000
```

如果后端没有启动，前端会自动进入 Mock 兜底模式。

打包命令：

```bash
cd frontend
npm run build
```

---

## 9. 和后端同学对接时需要确认的内容

前端需要后端保持或确认以下接口：

- `GET /api/status`: 返回系统状态和设备在线状态。
- `GET /api/gesture/current`: 返回 `gesture`、`confidence`、可选 `all_probs`、可选 `latency_ms`。
- `GET /api/sensors/live`: 返回左右 Micro:bit 加速度和手部检测状态。
- `GET /api/music/state`: 返回 Sonic Pi 实际音乐状态，包括 `playing`、`bpm`、`volume`、`energy`、`section`、`last_bar`、`last_beat`、`beat_strength`、`elapsed_seconds`、`duration_seconds`、`sonic_pi_connected`。
- `GET /api/pi/status`: 返回 Pi 网关连接状态和最近消息计数。
- `POST /api/sonic-pi/transport`: 接收播放、暂停、重置等动作，并返回更新后的音乐状态。

如果后端新增字段，建议按以下原则：

- 尽量只新增字段，不删除现有字段。
- 尽量把新字段放在现有对象下面。
- 数值单位要明确，尤其是加速度数据。
- `confidence` 建议统一为 `[0, 1]`，前端也兼容 `[0, 100]`。

---

## 10. 后续可能需要修改的前端项

这些不是当前阻塞项，可以等硬件和后端更稳定后再做：

| 事项 | 优先级 | 什么时候做 |
|---|---:|---|
| 增加 LED 灯带 / 矩阵预览面板 | 中 | 后端能提供 LED 状态或手势灯效状态后。 |
| 增加 ESP32 Gateway 状态显示 | 中 | 如果最终路演要明确展示 ESP32 链路。 |
| 接入 `/api/recording/start` 和 `/api/recording/stop` | 中 | 后端完成录制接口后。 |
| 接入 `/api/gesture/mappings` 手势映射表 | 低 | 后端完成映射接口后。 |
| 替换真实视频和照片素材 | 高 | 路演前素材录制完成后。 |
| 接入真实 Pi Camera 实时预览 | 可选 | 后端或 Pi 侧提供稳定视频流后。 |

---

## 11. 当前结论

当前前端已经可以用于：

- 打开并展示完整路演界面。
- 在没有硬件的情况下用 Mock 数据演示项目效果。
- 在后端启动后读取真实状态数据。
- 展示 Sonic Pi 播放状态、BPM、Bar/Beat 和音乐参数。
- 在硬件未完全稳定前保证界面观感和演示完整性。

后续前端修改原则：

```text
只有当后端 API 变化、真实素材准备好，或者团队决定增加 LED/ESP32/录制控制展示时，前端才需要继续修改。
```
