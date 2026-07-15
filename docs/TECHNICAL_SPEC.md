# Hardware Datasheet & Environment Spec — AIoT Smart Conducting System

> **版本**: v1.0 | **最后更新**: 2026-07-15

---

## 1. 硬件清单

| 序号 | 设备 | 数量 | 型号/规格 | 状态 | 负责人 |
|:--:|------|:--:|------|:--:|------|
| 1 | 主控板 | 1 | Raspberry Pi 5 8GB | ✅ 已领取 | 硬件 B |
| 2 | 微控制器 | 2 | Micro:bit v2 | ✅ 已领取 | 硬件 A |
| 3 | WiFi MCU | 1 | ESP32 Dev Board | ✅ 已领取 | 硬件 B |
| 4 | 摄像头 | 1 | Pi Camera Module (排线连接) | ⏳ 待到位 | 硬件 B |
| 5 | LED 矩阵 | 2 | 8×32 WS2812B (共 512 LEDs) | ⏳ 待到位 | 硬件 B |
| 6 | 传感器套件 | 1 | Standard Sensor Kit | ✅ 已领取 | 硬件 A |
| 7 | 电池盒 | 2 | Micro:bit 电池盒 (AAA×2) | ✅ 已领取 | 硬件 A |
| 8 | 腕带 | 2 | 松紧带/Velcro | 待制作 | 硬件 A |
| 9 | 电源 | 1 | Pi 5 USB-C 供电 | ✅ | 硬件 B |
| 10 | 电源 | 1 | ESP32 USB 供电 或 独立 5V | ✅ | 硬件 B |

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

### 2.3 ESP32

| 项目 | 参数 |
|------|------|
| 芯片 | ESP32-WROOM-32 |
| WiFi | 2.4 GHz 802.11 b/g/n |
| LED 驱动库 | FastLED 或 Adafruit NeoPixel |
| 通信 | MQTT Client → 订阅 Pi 5 Mosquitto |
| LED 数据引脚 | GPIO 可配（建议 GPIO 16/17） |
| 供电 | 5V (LED 矩阵独立供电，勿从 ESP32 3.3V 取) |

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

## 3. PC 开发环境（模型负责人）

| 软件 | 版本/用途 |
|------|------|
| Python | 3.10+ |
| MediaPipe | 0.10.x (Hand Landmarker) |
| OpenCV | 4.x (`opencv-python`) |
| bleak | 0.21+ (BLE 客户端) |
| scikit-learn | 1.3+ (Random Forest) |
| pandas | 2.x (数据处理) |
| NumPy | 1.24+ |
| Matplotlib | 3.7+ (可视化) |
| joblib | 1.3+ (模型持久化) |
| paho-mqtt | 1.6+ (MQTT 客户端) |

---

## 4. Pi 5 部署环境（后端 + 推理）

| 软件 | 用途 |
|------|------|
| Flask | 3.x (Web API) |
| Flask-CORS | 跨域支持 |
| Mosquitto | MQTT Broker |
| SQLite | 数据库 (Python 内置) |
| paho-mqtt | MQTT Client (Python) |

> **注意**：模型推理可以在 Pi 5 上直接跑，也可以在开发 PC 上跑，取决于性能。先按 PC 推理 → 后端同机部署开发，最终可迁移到 Pi 5。

---

## 5. WiFi / 网络拓扑

```
           教室 WiFi (或 Pi 5 热点)
                    │
        ┌───────────┼───────────┐
        ↓           ↓           ↓
     Pi 5         PC 开发机    ESP32
  (Mosquitto,   (模型推理,    (LED Matrix
   Flask API)   BLE 接收)     MQTT Client)
        │
   Pi Camera
  (排线直连)
```

| 设备 | 连接方式 | 网络 |
|------|----------|------|
| Pi 5 ↔ PC | WiFi / Ethernet | 同一局域网 |
| PC ↔ Micro:bit ×2 | **BLE** (不经过 WiFi) | 蓝牙直连 |
| Pi Camera ↔ Pi 5 | MIPI 排线 | 本地 |
| ESP32 ↔ Pi 5 | WiFi | 同一局域网 |
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
│   ├── esp32/              #   ESP32 固件 (.ino)
│   └── pi/                 #   Pi 5 配置脚本
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
