# Session Summary — AIoT Smart Conducting Performance System

> 最后更新：2026-07-22 (Pi 5 远程核查 + ESP32 纳入 BLE 方案)  
> 截止：**7月29日** 项目最终交付

---

## 硬件清单

| 硬件 | 用途 | 状态 |
|------|------|------|
| Micro:bit ×2 | 手腕加速度计 (A/B) | BLE 固件仍未解决 |
| Raspberry Pi 5 | 核心中枢 (MQTT/Dashboard/LED) | 环境就绪，服务未部署 |
| Pi Camera | MediaPipe 手势（暂缓） | 组员已测通 (rpicam) |
| WS2812B LED 矩阵 | 手势可视化 | 未接线，驱动库未装 |
| **ESP32** | **BLE→WiFi 桥接（新方案核心）** | 在配件中，未启用 |
| PC | RF 推理 (`pc_inference_bridge.py`) | 待测试 |

---

## 当前任务及进度

- [x] Micro:bit ×2 USB Serial 固件 50Hz (A+B)
- [x] PC 端接收模块 `microbit_receiver.py` (Serial + BLE)
- [x] 数据采集工具 `collect_data.py` (MediaPipe + Micro:bit 同步)
- [x] 特征工程: Camera 25维 + Accel 18维 + 滑动窗口 43维
- [x] 模型训练: RF + GridSearchCV (合成数据 100% 准确率)
- [x] Pi 5 脚本全部编写完成 (`pi5/` 共 14 个文件) 并上传到 `~/aiot_project/`
- [x] Pi 5: Mosquitto 运行中、venv 依赖已装、Flask Dashboard 曾验证通过
- [x] Pi 5 远程核查（7/22 下午，见下节）
- [ ] **Micro:bit BLE 数据传输（核心阻塞，见「BLE 解决方案」）**
- [ ] **ESP32 BLE→MQTT 桥接固件（新路线，待评估/编写）**
- [ ] Mosquitto 配置修复：当前仅监听 `127.0.0.1:1883`，PC 无法连接 → 需改 `listener 0.0.0.0`
- [ ] 部署 systemd 服务（已确认未注册）
- [ ] venv 补装 LED 库（`rpi_ws281x`/`adafruit-circuitpython-neopixel`）
- [ ] PC 端 `pc_inference_bridge.py` 测试
- [ ] LED WS2812B 硬件连接 + 测试 (GPIO18 → DIN)
- [ ] 端到端集成测试

---

## Pi 5 远程核查结果（7/22 下午，只读检查）

### 我方部署 (`~/aiot_project/`) — 文件完好，服务未动
- 14 个脚本 + systemd 配置 + 模型文件全部在位（7/22 12:42–13:30 上传）
- venv: Python 3.13.5, bleak 3.0.2, Flask 3.1.3, paho-mqtt 2.1.0 ✓
- **缺 LED 驱动库**（无 rpi_ws281x/adafruit/neopixel）→ `pi_led_driver.py` 暂时跑不起来
- Mosquitto 运行中，但 **只绑定 127.0.0.1:1883**（默认配置）→ PC 端连不上，必须改配置
- systemd 服务 **确认未注册**（4 个 unit 均 not found），无任何项目进程在跑

### 组员并行项目 (`~/aiot_conductor/project/`) — 7/22 当天活跃
- `microbit_to_Pi/`: 自己的 BLE 接收器（NUS，`config.json` 记录左右手 MAC：`E7:C8:C1:AF:21:46` / `FD:15:9A:47:7F:8F`）
- `camera_to_Pi/`: 独立 venv；已装 picamera2，`rpicam-hello` 测通
- `live_preview_server.py` (port 8787) + `microbit_receiver.app` 两个进程正在运行
- 系统层面：装了 xrdp / tightvncserver
- **注意**：组员走的是独立技术栈，与 `~/aiot_project` 的 MQTT 架构未打通，需要尽快对齐

---

## BLE 问题现状

**仍未解决。** 两边各自的进展：

- 我方结论（7/22 上午调试）：旧固件 NUS TX 发二进制（17字节，MakeCode 内部格式）；新固件 `ble_uart_final.js` 编译时蓝牙栈未包含（NUS UUID 为空，连接即断）
- 组员：自建 BLE 接收器 + 已知设备 MAC，在 Pi 上直接跑，但数据是否真正打通**未确认**

### 可选解决方案（按推荐度排序）

1. **ESP32 作为 BLE→WiFi/MQTT 桥接器（推荐）**
   - ESP32 用 NimBLE 作 BLE Central，同时连两块 Micro:bit，数据经 WiFi 直接发 MQTT 到 Pi（topic 与现有架构完全一致：`microbit/accel/A,B`）
   - 彻底绕开 Pi BlueZ 连接不稳定 + Windows BLE 不可用两个问题；`pc_inference_bridge` 等下游零改动
   - 成本：写一份 ~150 行 Arduino 固件 (NimBLE + PubSubClient)

2. **订阅标准加速度计 Service `E95D93AF`，放弃 NUS UART**
   - 旧固件已验证该服务存在且可发现；`pi5/ble_accel_test.py` 就是为这条路写的
   - 可在 Pi (BlueZ) 或 ESP32 上用；不依赖 MakeCode UART 文本格式

3. **修复 Micro:bit BLE 固件**
   - MakeCode 正确添加 bluetooth 扩展（与 radio 扩展互斥，需移除）；或改用 microPython 固件直接控制 NUS 文本输出

4. **保底：USB Serial 直连**
   - 固件和 `microbit_receiver.py` 都是现成的 50Hz 链路，演示可用；缺点是手腕拖线，表演效果打折

---

## Pi 5 部署文件清单

### 核心脚本 (`pi5/`)
| 文件 | 说明 |
|------|------|
| `pi_ble_receiver.py` | BLE → MQTT: 连接 Micro:bit ×2 (BlueZ)，发布到 `microbit/accel/A,B` |
| `pi_landmarks_publisher.py` | Pi Camera → MediaPipe Hands → MQTT（暂缓） |
| `pi_led_driver.py` | MQTT → WS2812B: 订阅 `model/gesture`，9 种手势对应 LED 动画 |
| `pi_flask_app.py` | Flask Dashboard: REST API + WebSocket + SQLite |
| `pc_inference_bridge.py` | PC 端: 订阅 MQTT → SlidingWindowMerger → RF 推理 → 发布 `model/gesture` |

### 测试脚本 (`pi5/`)
`ble_accel_test.py`（标准加速度计 Service）、`ble_deep_test.py`、`ble_dbus_connect.py`（D-Bus 直连）、`ble_scan.py`/`scan_mb.py`、`ble_connect_test.py`/`ble_quick_test.py`、`ble_verify.py`/`ble_verify_one.py`、`ble_hex_analyze.py`

### 部署配置 (`pi5/systemd/`)
`pi-ble-receiver.service`、`pi-flask.service`、`pi-led-driver.service`（需 root）、`pi-landmarks.service`（暂缓）

### MQTT Topic 架构
```
Pi 5 (Mosquitto Broker)
├── microbit/accel/A,B        ← pi_ble_receiver 或 ESP32 桥
├── microbit/status/A,B       ← 设备状态
├── model/gesture             ← pc_inference_bridge 发布
├── model/status              ← pc_inference_bridge 发布
├── led/command               ← pi_flask_app 发布
└── led/status                ← pi_led_driver 发布
```

### 数据格式
- **Accel**: `{"device_id":"A", "acc_x":1234, "acc_y":-56, "acc_z":789, "timestamp_ms":..., "pc_timestamp":..., "acc_norm":...}`
- **Gesture**: `{"gesture":"强拍", "confidence":0.95, "probabilities":{...}, "timestamp":..., "smoothed":true}`

---

## 架构（ESP32 路线，候选）

```
Micro:bit ×2 (BLE, 手腕)
    │  BLE (NUS 文本 / 加速度计 Service)
    ▼
ESP32 (BLE Central ×2 连接)
    │  WiFi MQTT → microbit/accel/A,B
    ▼
┌─────────────────────────────────────────────┐
│ Pi 5 (核心中枢)                              │
│  Mosquitto MQTT Broker                       │
│  ├─ pi_led_driver: MQTT Gesture → LED 动画  │
│  └─ pi_flask_app: Dashboard API + WebSocket │
└─────────────────────────────────────────────┘
    │  MQTT (WiFi)
    ▼
PC: pc_inference_bridge.py
    ├─ SlidingWindowMerger (500ms window)
    ├─ Random Forest 手势分类 (43维特征)
    └─ 发布 model/gesture → Pi 5 (LED 驱动)
```

（原 BlueZ 路线中 ESP32 位置由 `pi_ble_receiver.py` 替代，其余相同）

---

## 手势 → LED 动画对应表

| 手势 | LED 效果 |
|------|----------|
| 静止/Idle | 蓝色呼吸脉冲 |
| 开始/Start | 绿色从中心向外展开 |
| 停止/Stop | 红色闪 → 指数衰减 |
| 强拍/Downbeat | 白色从上到下移动 (attack-decay) |
| 弱拍/Upbeat | 柔和金色波纹 (bottom→top) |
| 渐强/Crescendo | 蓝色→青色→白色, 暗→亮 (3s 循环) |
| 渐弱/Diminuendo | 白色→青色→蓝色, 亮→暗 (3s 循环) |
| 左手提示/Left | 左矩阵蓝色闪烁, 右暗 |
| 右手提示/Right | 右矩阵蓝色闪烁, 左暗 |

---

## 下次启动待办

1. 与组员对齐：`~/aiot_conductor` 与 `~/aiot_project` 两套栈合并策略，确认 Micro:bit BLE 数据是否已打通
2. 决定 BLE 路线（推荐 ESP32 桥接）→ 编写 ESP32 固件
3. 修 Mosquitto 配置：`listener 1883 0.0.0.0` + `allow_anonymous true`，重启服务
4. venv 补装 LED 库；部署 systemd 服务
5. PC 运行 `pc_inference_bridge.py --broker 192.168.43.221`
6. LED 硬件接线测试（GPIO18 → WS2812B DIN）
7. 端到端测试: BLE → MQTT → 推理 → LED → Dashboard

---

## Pi 5 连接信息

```
SSH: ag1_client@192.168.43.221
密码: 见本地私有记录（不提交到仓库）
我方路径: ~/aiot_project/pi5/   venv: ~/aiot_project/venv/bin/python
组员路径: ~/aiot_conductor/project/
```
