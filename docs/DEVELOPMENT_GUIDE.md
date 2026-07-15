# Development Guide — AIoT Smart Conducting System

> **版本**: v1.0 | **最后更新**: 2026-07-15

本文档指导每位组员搭建自己的开发环境并完成第一项任务。

---

## 0. 全体组员 — 共同步骤

### 0.1 克隆仓库

```bash
git clone <repo-url>
cd AIoT
```

### 0.2 阅读必读文档

1. `docs/TECHNICAL_SPEC.md` — 了解硬件、拓扑、技术栈
2. `docs/INTERFACE_CONTRACT.md` — 找到你负责的接口章节，**严格按约定格式开发**

### 0.3 沟通频道

- 微信群：日常沟通
- 接口问题：在 `docs/INTERFACE_CONTRACT.md` 对应章节提 issue/PR
- 不要口头约定接口，必须更新文档

---

## 1. 模型负责人（王祎哲）— 环境搭建

> **开发机**：自己的 PC 笔记本  
> **目标**：MediaPipe + Micro:bit BLE + Random Forest 完整 pipeline

### 1.1 安装 Python 依赖

```bash
pip install mediapipe opencv-python bleak scikit-learn pandas numpy joblib matplotlib paho-mqtt
```

### 1.2 验证 MediaPipe（用笔记本摄像头）

创建 `model/test_mediapipe.py`：
```python
import cv2
import mediapipe as mp

mp_hands = mp.solutions.hands
hands = mp_hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.7)
mp_draw = mp.solutions.drawing_utils

cap = cv2.VideoCapture(0)  # 笔记本摄像头 / Pi Camera 到位后也是 0
while cap.isOpened():
    ret, frame = cap.read()
    if not ret: break
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = hands.process(rgb)
    if result.multi_hand_landmarks:
        for hand_landmarks in result.multi_hand_landmarks:
            mp_draw.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)
    cv2.imshow("MediaPipe Hands", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'): break
cap.release()
cv2.destroyAllWindows()
```

**验收标准**：摄像头画面显示 21 个手部关键点连线，双手同时检测，画面流畅 (30 FPS)。

### 1.3 Micro:bit BLE 接收测试

1. 在 [MakeCode](https://makecode.microbit.org/) 编写加速度 BLE UART 发送固件
2. 刷入两个 Micro:bit（分别写入 device_id "L" 和 "R" 标识）
3. 用手机 BLE Scanner (nRF Connect) 验证广播
4. PC 端写 `model/ble_receiver.py`，使用 `bleak` 连接双设备并打印实时数据

**验收标准**：终端同时打印两台 Micro:bit 的 `acc_x, acc_y, acc_z, timestamp`。

### 1.4 第一周目标

- [ ] MediaPipe 环境验证 ✅
- [ ] 双 Micro:bit BLE 连接 + 数据接收 ✅
- [ ] 数据采集工具（CLI 或 GUI）
- [ ] 采集手势样本数据（拉全组帮忙录）
- [ ] 特征提取脚本

---

## 2. 后端负责人 — 环境搭建

> **开发机**：自己的 PC（最终部署到 Pi 5）  
> **目标**：Flask API + SQLite + MQTT Client

### 2.1 安装依赖

```bash
pip install flask flask-cors paho-mqtt
```

SQLite 是 Python 内置模块，无需额外安装。

### 2.2 创建 Flask 骨架

在 `backend/` 下创建 `app.py`，先实现三个端点：

```python
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/api/status')
def status():
    return jsonify({"status": "ok", "camera_connected": False, "model_loaded": False})

@app.route('/api/gesture/current')
def gesture_current():
    # 先返回假数据，等模型接口就绪后替换为实际调用
    return jsonify({"gesture": "idle", "confidence": 0.0, "timestamp": 0})

@app.route('/api/sensors/live')
def sensors_live():
    return jsonify({
        "microbit_left": {"acc_x": 0, "acc_y": 0, "acc_z": 0},
        "microbit_right": {"acc_x": 0, "acc_y": 0, "acc_z": 0},
        "hand_detected": False
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

**验收标准**：`python app.py` → 浏览器打开 `http://localhost:5000/api/status` 返回 JSON。

### 2.3 数据库初始化

创建 `backend/database.py`，在应用启动时建表。表结构见 `INTERFACE_CONTRACT.md` 第 6 节。

### 2.4 第一周目标

- [ ] Flask 骨架跑通 ✅
- [ ] SQLite 建表 + 写入测试
- [ ] MQTT Client 连接 Pi 5 Mosquitto
- [ ] `/api/gesture/current` 接入模型推理模块（模型交付后）
- [ ] `/api/gesture/history` 从 DB 查询历史

---

## 3. 前端负责人 — 环境搭建

> **开发机**：自己的 PC（浏览器打开 HTML）  
> **目标**：Dashboard 静态页面 + 接入后端 API + Web Audio API

### 3.1 技术栈

- 纯 HTML + CSS + JavaScript（无需 Node.js / 构建工具）
- Chart.js CDN 引入
- Web Audio API (浏览器内置)

### 3.2 创建 Dashboard 骨架

在 `frontend/` 下创建 `index.html`，包含以下面板：

| 面板 | 内容 | 数据来源 |
|------|------|----------|
| 手势状态 | 当前手势名称 + 置信度 | `GET /api/gesture/current` |
| 概率雷达图 | 所有手势概率分布 (Chart.js radar) | `all_probs` 字段 |
| 传感器数值 | L/R acc 实时仪表 | `GET /api/sensors/live` |
| 音乐状态 | BPM / 音量 / 风格 | `GET /api/music/state` |
| 手势历史 | 最近 20 条记录表格 | `GET /api/gesture/history` |

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>AIoT Conducting Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
</head>
<body>
    <h1>🎼 AIoT Smart Conducting Dashboard</h1>
    <!-- 各面板区域，用 fetch() 定时拉后端 API -->
</body>
</html>
```

### 3.3 Web Audio API 测试

写一个独立测试页面：点击按钮播放正弦波，验证 `AudioContext` 可用。

```javascript
const ctx = new AudioContext();
const osc = ctx.createOscillator();
osc.type = 'sine';
osc.frequency.value = 440;
osc.connect(ctx.destination);
osc.start();
osc.stop(ctx.currentTime + 1);
```

### 3.4 第一周目标

- [ ] Dashboard 静态布局完成 ✅
- [ ] 接 `/api/status` 验证连通 ✅
- [ ] Chart.js 各图表渲染（用假数据）
- [ ] Web Audio API 基础播放控制
- [ ] 接入真实 API（后端交付后）

---

## 4. 硬件 A（Micro:bit + 腕带 + 传感器）— 环境搭建

> **开发工具**：MakeCode (https://makecode.microbit.org/) 或 MicroPython  
> **目标**：Micro:bit ×2 BLE UART 加速度流 + 腕带制作

### 4.1 Micro:bit 固件需求

**MakeCode 实现要点**：

```
- 开机后启动 BLE UART Service
- 在 forever 循环中读取加速度 (mg 单位)
- 每 20ms (50Hz) 通过 BLE UART Write 发送一行 CSV:
  "L,acc_x,acc_y,acc_z,running_time_ms"
- 左设备 device_id = "L"，右设备 = "R"
- 电池供电时 LED 显示不同图案区分左右
```

**MakeCode 扩展**：需要添加 Bluetooth 扩展包。

### 4.2 MakeCode 关键 Blocks

```
on start:
    bluetooth uart service start
    set device_id = "L"  (或 "R")

forever:
    acc_x = acceleration (mg) x
    acc_y = acceleration (mg) y
    acc_z = acceleration (mg) z
    data = device_id + "," + acc_x + "," + acc_y + "," + acc_z + "," + running_time_ms
    bluetooth uart write line data
    pause 20
```

### 4.3 验收标准

1. 手机 nRF Connect 扫描到 Micro:bit 广播
2. 连接到 BLE UART Service
3. 订阅 TX Characteristic → 看到持续的数据流
4. 甩动 Micro:bit → 加速度值剧烈变化

### 4.4 腕带制作

- 材料：松紧带 / Velcro 魔术贴 / 橡皮筋
- 要求：Micro:bit 紧贴手腕背部，甩动时不移位
- 方向：Micro:bit LED 面朝外，USB 口朝向手指

### 4.5 第一周目标

- [ ] 两个 Micro:bit 均刷入固件 ✅
- [ ] BLE 广播验证 ✅
- [ ] 腕带制作完成
- [ ] 配合模型负责人验证 PC 端 BLE 接收
- [ ] （可选）Sensor Kit 中有用的传感器探索

---

## 5. 硬件 B（Pi 5 + ESP32 + LED Matrix + Camera）— 环境搭建

> **开发工具**：Pi Imager, Arduino IDE, Python  
> **目标**：Pi 5 就绪 + ESP32 LED 驱动 + Camera 验证

### 5.1 Pi 5 初始化

```bash
# 1. 用 Raspberry Pi Imager 刷 Pi OS (64-bit Bookworm)
# 2. 开机后配置：
sudo apt update && sudo apt upgrade -y
sudo apt install mosquitto mosquitto-clients -y
sudo systemctl enable mosquitto

# 3. 测试 Mosquitto：
mosquitto_sub -t "test" &
mosquitto_pub -t "test" -m "hello"
# 终端应打印 "hello"

# 4. 固定 IP（或确认教室 IP 分配）：
# 记下 Pi 5 的 IP 地址：hostname -I

# 5. 确认 Pi Camera 排线物理连接正确后：
libcamera-hello --list-cameras
# 应列出 Pi Camera 设备
```

### 5.2 ESP32 — LED Matrix 驱动

**推荐库**：FastLED (Arduino Library Manager 安装)

**接线**：
```
ESP32 GPIO16 → WS2812B Panel 1 DIN
Panel 1 DOUT → Panel 2 DIN
5V 外部电源 → 两个 Panel VCC + GND
ESP32 GND → 两个 Panel GND (共地)
```

**测试代码骨架**（Arduino）：
```cpp
#include <FastLED.h>
#define LED_PIN 16
#define NUM_LEDS 512   // 2 × 256
CRGB leds[NUM_LEDS];

void setup() {
    FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, NUM_LEDS);
    FastLED.setBrightness(30);  // 限制亮度，避免大电流
}

void loop() {
    // 测试：全红 → 全绿 → 全蓝
    fill_solid(leds, NUM_LEDS, CRGB::Red);
    FastLED.show(); delay(1000);
    fill_solid(leds, NUM_LEDS, CRGB::Green);
    FastLED.show(); delay(1000);
    fill_solid(leds, NUM_LEDS, CRGB::Blue);
    FastLED.show(); delay(1000);
}
```

### 5.3 ESP32 — MQTT 连接

在 ESP32 上添加 WiFi + PubSubClient 库，订阅 `aiot/gesture` topic，收到消息后解析 JSON 并触发对应 LED 效果。

### 5.4 第一周目标

- [ ] Pi 5 刷系统 + Mosquitto 运行 ✅
- [ ] Pi Camera 验证 (libcamera-hello) ✅
- [ ] ESP32 点亮两块 LED Matrix ✅
- [ ] ESP32 MQTT 连接 Pi 5 Broker + 订阅 `aiot/gesture`
- [ ] 根据手势 JSON 触发不同 LED 效果

---

## 6. 第一周里程碑检查点（7月21日）

| 模块 | 检查项 | 验收方式 |
|------|--------|----------|
| 模型 | MediaPipe 双手检测 30FPS | 运行脚本 + 截图 |
| 模型 | 双 Micro:bit BLE 数据流 | 终端 log 截图 |
| 后端 | Flask 5 个端点返回 JSON | `curl` + 浏览器 |
| 前端 | Dashboard 静态页面 + Chart.js 图表 | 浏览器截图 |
| 硬件 A | 双 Micro:bit BLE 广播 | nRF Connect 截图 |
| 硬件 B | Pi 5 Mosquitto + Pi Camera 驱动 | `libcamera-hello` 输出 |
| 硬件 B | ESP32 点亮 LED Matrix | 视频/照片 |

---

> ⚠️ **遇到阻塞？**  
> 1. 先查本文档 + `INTERFACE_CONTRACT.md`  
> 2. 微信群问  
> 3. 更新 `session-summary.md` 记录阻塞问题
