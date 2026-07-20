# Hardware Datasheet & Environment Spec — AIoT Smart Conducting System

> **版本**: v1.0 | **最后更新**: 2026-07-15

---

## 1. 硬件清单

| 序号 | 设备 | 数量 | 型号/规格 | 状态 | 负责人 |
|:--:|------|:--:|------|:--:|------|
| 1 | 主控板 | 1 | Raspberry Pi 5 8GB | ✅ 已领取 | 硬件 B |
| 2 | 微控制器 | 2 | Micro:bit v2 | ✅ 已领取 | 硬件 A |
| 3 | 摄像头 | 1 | Pi Camera Module (排线连接) | ⏳ 待到位 | 硬件 B |
| 4 | LED 矩阵 | 2 | 8×32 WS2812B (共 512 LEDs) | ⏳ 待到位 | 硬件 B |
| 5 | 传感器套件 | 1 | Standard Sensor Kit | ✅ 已领取 | 硬件 A |
| 6 | 电池盒 | 2 | Micro:bit 电池盒 (AAA×2) | ✅ 已领取 | 硬件 A |
| 7 | 腕带 | 2 | 松紧带/Velcro | 待制作 | 硬件 A |
| 8 | 电源 | 1 | Pi 5 USB-C 供电 | ✅ | 硬件 B |
| 9 | 电源 | 1 | LED 矩阵 5V 独立供电 | ⏳ 待到位 | 硬件 B |

---

## 2. 各硬件关键参数

### 2.1 Raspberry Pi 5 (8GB)

| 项目 | 参数 |
|------|------|
| OS | Raspberry Pi OS (Bookworm, 64-bit) |
| Python | 3.11+ |
| 关键软件 | Mosquitto MQTT Broker, OpenCV, bleak |
| IP | 静态 IP（连入教室 WiFi 后固定） |
| 摄像头接口 | 15-pin MIPI CSI 排线 |
| GPIO 用途 | 可选：外接按钮触发演示 |

### 2.2 Micro:bit v2 ×2

| 项目 | 参数 |
|------|------|
| CPU | nRF52833 (ARM Cortex-M4, 64MHz) |
| 加速度计 | LSM303AGR (3 轴, ±2/4/8g) |
| 采样率 | **50 Hz** (BLE UART 发送间隔 20ms) |
| BLE | Bluetooth 5.1, UART Service |
| 固件语言 | MakeCode (JavaScript) 或 MicroPython |
| 供电 | AAA×2 电池盒 (3V) |
| 佩戴方式 | 腕带固定于左右手腕 |

### 2.3 Pi 5 直驱 WS2812B LED Matrix

| 项目 | 参数 |
|------|------|
| 驱动方式 | Pi 5 GPIO18 (PWM) 直连 LED Matrix DATA 脚 |
| LED 驱动库 | `rpi_ws281x` (Python) |
| 供电 | **LED 矩阵 5V 独立供电**（512 LEDs 全亮 ~30W，勿从 Pi 5 取电） |
| 共地 | Pi 5 GND ↔ LED Matrix GND |
| 接线 | GPIO18 → Panel 1 DIN → Panel 1 DOUT → Panel 2 DIN |

> **为什么不用 ESP32**：Pi 5 可直接驱动 WS2812B，减少一套开发环境、通信链路和故障点。后端 Python 代码直接调 `rpi_ws281x` 控制 LED，无需 MQTT 中转。

### 2.4 WS2812B LED Matrix (2× 8×32)

| 项目 | 参数 |
|------|------|
| LED 型号 | WS2812B (NeoPixel 兼容) |
| 单块尺寸 | 8 行 × 32 列 = 256 LEDs |
| 总量 | 2 块 = **512 LEDs** |
| 排列方式 | 串联：Panel 1 DOUT → Panel 2 DIN |
| 供电 | **5V, 约 30W** (512×60mA 最大) |
| 协议 | 单线 NZR (800 Kbps) |

> ⚠️ **供电警告**：512 个 WS2812B 全白时电流可达 30A (150W)，需要独立 5V 电源。演示时限制亮度可大幅降低功耗。

### 2.5 Pi Camera

| 项目 | 参数 |
|------|------|
| 接口 | MIPI CSI-2 (15-pin 排线) |
| 分辨率 | 建议 640×480 (与 MediaPipe 平衡速度和精度) |
| 帧率 | 30 FPS |
| OpenCV 索引 | `cv2.VideoCapture(0)` (Pi 5 上通常是 0) |

---

## 3. PC 开发环境（模型负责人 — 手势分类 + BLE）

> **注意**：MediaPipe Hands 已移至 Pi 5 端运行，PC 只做 Random Forest 分类 + BLE 接收。

| 软件 | 版本/用途 |
|------|------|
| Python | 3.10+ |
| scikit-learn | 1.3+ (Random Forest 手势分类) |
| pandas | 2.x (数据处理) |
| NumPy | 1.24+ |
| Matplotlib | 3.7+ (可视化) |
| joblib | 1.3+ (模型持久化) |
| bleak | 0.21+ (BLE 客户端，接收 Micro:bit) |
| paho-mqtt | 1.6+ (MQTT 客户端：订阅 Pi 5 landmarks，发布 gesture 结果) |
| OpenCV | 4.x (仅开发/调试用，非运行时依赖) |
| MediaPipe | 0.10.x (仅训练阶段特征分析用，非运行时依赖) |

---

## 4. Pi 5 部署环境（后端 + MediaPipe + LED 驱动）

| 软件 | 用途 |
|------|------|
| Flask | 3.x (Web API) |
| Flask-CORS | 跨域支持 |
| Mosquitto | MQTT Broker |
| SQLite | 数据库 (Python 内置) |
| paho-mqtt | MQTT Client (Python) |
| MediaPipe | 0.10.x (Hand Landmarker — 手部 21 关键点提取) |
| OpenCV | 4.x (Pi Camera 图像采集) |
| rpi_ws281x | LED Matrix 直驱 |

> **架构决策 (2026-07-20)**：MediaPipe Hands 在 Pi 5 本地运行。Pi Camera 图像不再传输到 PC，而是 Pi 5 本地提取 21 个手部关键点后，仅将 landmarks JSON 通过 MQTT 发送给 PC 做 Random Forest 手势分类。这样大幅降低网络带宽需求（~2KB/帧 vs 原始视频流）。

---

## 5. WiFi / 网络拓扑

```
           教室 WiFi
              │
    ┌─────────┼─────────┬──────────────┐
    ↓         ↓         ↓              ↓
  Pi 5       PC        Dashboard     Micro:bit ×2
 (Mosquitto, (RF 手势  前端          (BLE 直连 PC,
  Flask API,  分类,    (Chart.js,    不经过 WiFi)
  MediaPipe,  BLE 接收) Web Audio)
  LED Matrix
  直驱 GPIO)
    │
 Pi Camera
(排线直连)
```

**数据流：**
```
Pi Camera → Pi 5 (MediaPipe Hands)
                │
                ↓ MQTT: pi/hand_landmarks (JSON, ~30Hz)
                │
           PC (Random Forest 分类) ← BLE ← Micro:bit ×2 (50Hz)
                │
                ↓ MQTT: model/gesture (JSON)
                │
           Pi 5 (Flask API → Dashboard / SQLite / LED Matrix)
```

| 设备 | 连接方式 | 网络 |
|------|----------|------|
| Pi 5 ↔ PC | WiFi | 同一局域网 (MQTT) |
| PC ↔ Micro:bit ×2 | **BLE** (不经过 WiFi) | 蓝牙直连 |
| Pi Camera ↔ Pi 5 | MIPI 排线 | 本地 |
| LED Matrix ↔ Pi 5 | GPIO 直连 | 本地 |
| 前端 Dashboard ↔ Pi 5 | WiFi HTTP | 同一局域网 |

---

## 6. 项目 Git 仓库

```
AIoT/
├── model/                  # 模型负责（王祎哲）
│   ├── data_collection/    #   数据采集脚本
│   ├── feature_engineering/#   特征提取
│   ├── training/           #   模型训练
│   ├── inference/          #   实时推理 pipeline
│   ├── models/             #   训练好的 .pkl 文件 (Git LFS 或 .gitignore)
│   └── ble_receiver.py     #   Micro:bit BLE 接收
├── backend/                # 后端负责
│   ├── app.py              #   Flask 入口
│   ├── database.py         #   SQLite 操作
│   ├── mqtt_client.py      #   MQTT 发布
│   └── requirements.txt
├── frontend/               # 前端负责
│   ├── index.html          #   Dashboard 主页
│   ├── js/
│   │   └── dashboard.js    #   Chart.js 图表
│   └── css/
│       └── style.css
├── hardware/               # 硬件组
│   ├── microbit/           #   Micro:bit 固件 (.hex / .py)
│   └── pi/                 #   Pi 5 配置 + LED 驱动脚本
├── data/                   # 数据 (Git 忽略)
│   ├── raw/
│   └── processed/
├── docs/                   # 文档
│   ├── INTERFACE_CONTRACT.md
│   ├── TECHNICAL_SPEC.md
│   └── DEVELOPMENT_GUIDE.md
├── .gitignore
└── README.md
```
