# Interface Contract — AIoT Smart Conducting System

> **版本**: v1.0  
> **最后更新**: 2026-07-15  
> **维护人**: 王祎哲 (模型负责 + 组长)  
> **用途**: 定义各模块间的数据接口、传输方式、数据格式。**所有组员在开发前必须阅读对应的接口章节。**

---

## 1. 系统接口总图

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐     ┌──────────────┐
│  Micro:bit×2 │────▶│  PC (模型推理)    │────▶│  Flask 后端  │────▶│  SQLite DB   │
│  BLE UART    │ ①   │  MediaPipe       │ ③   │  Pi 5        │ ⑤   │              │
└─────────────┘     │  + Random Forest  │     └──────┬───────┘     └──────────────┘
                    └──────────────────┘            │ ④
        ┌──────────┐                               ├──────────────▶  Dashboard 前端
        │ Pi Camera│──────────────────────────────▶│                  (Chart.js)
        └──────────┘  ②                            │ ⑥
                                                   └──────────────▶  Pi 5 GPIO → LED Matrix
                                                                     (rpi_ws281x 直驱)
```

| 编号 | 方向 | 传输方式 | 责任人 |
|:--:|------|----------|--------|
| ① | Micro:bit → PC | BLE UART (无线) | 硬件 A → 模型 |
| ② | Pi Camera → PC | 排线 (本地) | 硬件 B → 模型 |
| ③ | 模型 → 后端 | Python import (同进程) | 模型 → 后端 |
| ④ | 后端 → 前端 | HTTP REST API | 后端 → 前端 |
| ⑤ | 后端 → 数据库 | SQLite (本地文件) | 后端 |
| ⑥ | 后端 → LED Matrix | Pi 5 GPIO 直驱 (`rpi_ws281x`) | 后端 → 硬件 B |

---

## 2. 接口 ① — Micro:bit BLE → PC

### 2.1 硬件参数

| 参数 | 值 |
|------|-----|
| 设备 | Micro:bit v2 ×2 |
| 佩戴 | 左右手腕 (使用腕带) |
| 传输协议 | BLE UART Service |
| 采样率 | **50 Hz** (每 20ms 一包) |
| 数据维度 | 三轴加速度 (acc_x, acc_y, acc_z) + 设备 ID |

### 2.2 BLE UART Service UUID

```
Service UUID:  6E400001-B5A3-F393-E0A9-E50E24DCCA9E
TX Characteristic: 6E400002-B5A3-F393-E0A9-E50E24DCCA9E  (Micro:bit → PC, 可 Notify)
RX Characteristic: 6E400003-B5A3-F393-E0A9-E50E24DCCA9E  (PC → Micro:bit, 可 Write)
```

### 2.3 数据格式（Micro:bit 端固件输出）

Micro:bit 固件通过 BLE UART TX 以 **CSV 文本行** 发送，每行一包：

```
L,acc_x,acc_y,acc_z,timestamp_ms
```

| 字段 | 类型 | 单位 | 说明 |
|------|------|------|------|
| `device_id` | string | — | `"L"` 左手, `"R"` 右手 |
| `acc_x` | float | mg | X 轴加速度（侧向） |
| `acc_y` | float | mg | Y 轴加速度（前后） |
| `acc_z` | float | mg | Z 轴加速度（上下） |
| `timestamp_ms` | int | ms | Micro:bit `running_time()` 毫秒时间戳 |

示例：
```
L,-128,32,-1024,1234567
R,64,-16,-980,1234569
```

### 2.4 PC 端接收规范

- 使用 Python `bleak` 库
- 连接两个 Micro:bit，分别订阅 TX Characteristic 的 Notify
- 每条消息加入 PC 本地时间戳（用于与 Camera 帧对齐）
- 输出格式（供模型消费）：

```json
{
  "device_id": "L",
  "acc_x": -128,
  "acc_y": 32,
  "acc_z": -1024,
  "microbit_ts": 1234567,
  "pc_ts": 1721052000.123456
}
```

---

## 3. 接口 ② — Pi Camera → MediaPipe (PC)

### 3.1 硬件参数

| 参数 | 值 |
|------|-----|
| 设备 | Raspberry Pi Camera Module 3 或兼容 |
| 分辨率 | 640×480 (可调整) |
| 帧率 | **30 FPS** |
| 连接 | Pi 5 排线接口 → OpenCV `cv2.VideoCapture(0)` |

### 3.2 MediaPipe 输出

每帧对每只手输出 **21 个关键点**（x, y, z），模型负责人封装为 Python 字典：

```json
{
  "frame_id": 1234,
  "pc_ts": 1721052000.123000,
  "hands": [
    {
      "handedness": "Left",
      "score": 0.98,
      "landmarks": [
        {"id": 0, "x": 0.512, "y": 0.623, "z": -0.012},
        {"id": 1, "x": 0.501, "y": 0.589, "z": -0.008},
        "... 共 21 个 ..."
      ]
    }
  ]
}
```

> **前端/后端不需要直接消费此格式**。这是模型内部的中间数据，模型推理后只输出最终手势结果。

---

## 4. 接口 ③ — 模型推理 → 后端

### 4.1 调用方式

后端 `import` 模型推理模块，直接调用函数：

```python
from model.inference import GestureClassifier

classifier = GestureClassifier(model_path="model/models/gesture_classifier.pkl")
result = classifier.predict(window_data)
```

### 4.2 输入格式（后端给模型）

后端将当前滑动窗口数据打包为 **NumPy feature vector**（由模型负责人定义特征列）：

```python
# 特征向量 shape: (n_features,)
# 包含: 手部空间特征(从MediaPipe提取) + acc特征(从Micro:bit提取) + 统计量
window_data = np.array([...])  # 具体特征列表见 TECH_SPEC.md
```

后端**不需要知道具体特征含义**，只需把收到的传感器数据传入推理模块即可。

### 4.3 输出格式（模型返回给后端） ⭐ 关键

```json
{
  "gesture": "downbeat",
  "confidence": 0.92,
  "gesture_id": 1,
  "timestamp": 1721052000.500000,
  "features_used": 38,
  "all_probs": {
    "idle": 0.01,
    "downbeat": 0.92,
    "crescendo": 0.02,
    "decrescendo": 0.01,
    "cutoff": 0.01,
    "style_switch": 0.01,
    "tempo_up": 0.01,
    "tempo_down": 0.01
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `gesture` | string | 手势类别名称 |
| `confidence` | float (0–1) | 模型置信度 |
| `gesture_id` | int | 手势类别编号 (0=idle, 1=downbeat, ...) |
| `timestamp` | float | 推理时刻 PC 时间戳 |
| `features_used` | int | 实际使用的特征数（可能因数据不足少于全量） |
| `all_probs` | dict | 所有类别的概率分布（用于 Dashboard 可视化） |

### 4.4 手势类别枚举

| gesture_id | gesture | 说明 | 音乐效果 |
|:--:|------|------|------|
| 0 | `idle` | 无手势/待机 | 无变化 |
| 1 | `downbeat` | 下拍 | 触发节拍/音符 |
| 2 | `crescendo` | 渐强 | 音量增大 |
| 3 | `decrescendo` | 渐弱 | 音量减小 |
| 4 | `cutoff` | 切断 | 停止当前音 |
| 5 | `style_switch` | 风格切换 | 切换音色 |
| 6 | `tempo_up` | 加速 | BPM +5 |
| 7 | `tempo_down` | 减速 | BPM -5 |

---

## 5. 接口 ④ — 后端 → 前端 (REST API)

### 5.1 基础约定

| 项目 | 值 |
|------|-----|
| 协议 | HTTP/1.1 |
| 数据格式 | JSON |
| Base URL | `http://<Pi5-IP>:5000/api` |
| 实时推送 | Server-Sent Events (SSE) 或 WebSocket，v1 先用轮询 |

### 5.2 API 端点

#### `GET /api/status`
系统状态检查。

**Response:**
```json
{
  "status": "ok",
  "camera_connected": true,
  "microbit_left": true,
  "microbit_right": true,
  "model_loaded": true,
  "uptime_seconds": 3600
}
```

#### `GET /api/gesture/current`
获取当前最新一次手势推理结果。

**Response:**
```json
{
  "gesture": "downbeat",
  "confidence": 0.92,
  "all_probs": { "...": "..." },
  "timestamp": 1721052000.500000
}
```

#### `GET /api/gesture/history?limit=20&since=1721052000`
获取历史手势记录。

**Response:**
```json
{
  "count": 20,
  "records": [
    {
      "id": 1001,
      "gesture": "downbeat",
      "confidence": 0.92,
      "timestamp": 1721052000.500000
    }
  ]
}
```

#### `GET /api/sensors/live`
获取实时传感器数值。

**Response:**
```json
{
  "microbit_left": {"acc_x": -128, "acc_y": 32, "acc_z": -1024},
  "microbit_right": {"acc_x": 64, "acc_y": -16, "acc_z": -980},
  "hand_detected": true,
  "hand_count": 2,
  "timestamp": 1721052000.500000
}
```

#### `GET /api/music/state`
获取当前音乐播放状态。

**Response:**
```json
{
  "playing": true,
  "bpm": 120,
  "volume": 0.8,
  "style": "piano",
  "current_gesture": "downbeat"
}
```

### 5.3 前端轮询建议

- `/api/gesture/current`: **100ms** 间隔（与推理 pipeline 同步）
- `/api/sensors/live`: **200ms** 间隔
- `/api/gesture/history`: 用户点击时拉取

---

## 6. 接口 ⑤ — 后端 → SQLite

### 6.1 数据库文件

```
d:\CC\AIoT\data\aiot.db
```

### 6.2 表结构草案（后端负责最终实现）

```sql
-- 原始传感器记录
CREATE TABLE sensor_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pc_ts REAL NOT NULL,
    device_id TEXT NOT NULL,       -- 'L' / 'R' / 'camera'
    acc_x REAL, acc_y REAL, acc_z REAL,
    hand_data TEXT,                 -- JSON, Camera 时才填充
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 手势推理记录
CREATE TABLE predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pc_ts REAL NOT NULL,
    gesture TEXT NOT NULL,
    confidence REAL NOT NULL,
    all_probs TEXT NOT NULL,        -- JSON
    features_used INTEGER,
    latency_ms REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 演示会话
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    total_predictions INTEGER DEFAULT 0
);
```

---

## 7. 接口 ⑥ — 后端 → LED Matrix (Pi 5 GPIO 直驱)

> **说明**：Pi 5 通过 GPIO18 直接驱动 WS2812B LED Matrix，无需 MQTT 中转。后端调用 `rpi_ws281x` 库控制灯光效果。

### 7.1 硬件连接

| 参数 | 值 |
|------|-----|
| 主控 | Raspberry Pi 5 |
| LED 型号 | WS2812B (2× 8×32 = 512 LEDs) |
| 数据引脚 | GPIO18 (PWM) |
| 驱动库 | `rpi_ws281x` (Python) |
| 供电 | 5V 独立电源（勿从 Pi 5 取电） |

### 7.2 后端调用方式

后端 Flask 路由在收到手势推理结果后，直接调用 LED 控制模块：

```python
# backend/led_controller.py
from rpi_ws281x import Adafruit_NeoPixel, Color

class LEDController:
    def __init__(self, led_count=512, led_pin=18, brightness=100):
        self.strip = Adafruit_NeoPixel(
            led_count, led_pin, 800000, 10, False, brightness
        )
        self.strip.begin()
    
    def trigger(self, gesture: str):
        """根据手势触发对应 LED 效果"""
        effects = {
            "idle":          self._breathing,
            "downbeat":      self._flash_white,
            "crescendo":     self._brightness_ramp_up,
            "decrescendo":   self._brightness_ramp_down,
            "cutoff":        self._instant_black,
            "style_switch":  self._palette_switch,
            "tempo_up":      self._fast_pulse,
            "tempo_down":    self._slow_pulse,
        }
        effect = effects.get(gesture, self._breathing)
        effect()
```

### 7.3 手势 ↔ LED 效果映射

| 手势 | LED Matrix 效果 | 说明 |
|------|----------------|------|
| `idle` | 慢呼吸脉冲 (4s 周期, 20%↔40% 亮度) | 待命中 |
| `downbeat` | 全屏白光闪烁 (100ms) | 节拍锚点 |
| `crescendo` | 亮度从下到上递增, 暗蓝→亮紫→亮红 | 力度可视化 |
| `decrescendo` | 亮度从上到下递减, 亮红→暗紫→暗蓝 | 渐弱可视化 |
| `cutoff` | 瞬间全黑 (0.5s 后恢复) | 果断切断 |
| `style_switch` | 调色板切换 (暖金↔冷蓝↔霓虹) | 风格可视化 |
| `tempo_up` | 脉冲/波浪频率同步 BPM 增加, 色相偏暖 | 加速反馈 |
| `tempo_down` | 脉冲/波浪频率同步 BPM 降低, 色相偏冷 | 减速反馈 |

> LED Matrix 排列：2× 8×32 WS2812B（共 512 LEDs），详情见 `TECHNICAL_SPEC.md` 第 2.4 节。完整手势→音乐→灯光映射方案见 `docs/GESTURE_MUSIC_LED_MAPPING.md`。

---

## 8. 接口变更流程

1. 发现问题 → 在对应接口章节提 issue
2. 组长评估影响范围
3. 更新本文档 → 通知受影响方
4. 双方同步修改代码

> **原则：先改文档，再改代码。不口头约定接口。**
