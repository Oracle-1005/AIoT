# micro:bit v2 广播、ESP32 网关与摄像头数据整理说明

本文档说明当前双 micro:bit v2 采用 BLE 广播，经 ESP32 转 UDP 到树莓派，并在树莓派上与摄像头 MediaPipe 手部关键点数据一起整理的执行方式和数据接口。

## 1. 当前推荐链路

```text
left micro:bit v2
  -> BLE advertising / Eddystone UID
right micro:bit v2
  -> BLE advertising / Eddystone UID
ESP32
  -> scan advertisements
  -> restore project micro:bit packet
  -> UDP gateway frame, port 17778
Raspberry Pi
  -> esp32_gateway_receiver
  -> JSON Lines microbit_sensor_state / microbit_control_event
Camera on Raspberry Pi
  -> Picamera2
  -> MediaPipe Hand Landmarker
  -> JSON Lines camera_landmark_frame
Fusion on Raspberry Pi
  -> align by Pi monotonic timestamp
  -> JSON Lines fused_frame / control_event / status
```

这个方案不再让树莓派或 ESP32 主动连接两块 micro:bit。micro:bit 只广播，ESP32 只扫描，因此不会再出现旧 GATT 方案中的“绝大多数时间连接失败”。需要接受的代价是 BLE 广播没有确认机制，偶发 `sequence_gap` 属于正常丢广播包。

## 2. 可执行预览方式

先确认 ESP32 已经上传网关固件，Wi-Fi 已连接到与树莓派相同网络，两块 micro:bit v2 已烧录广播固件并上电。

在树莓派上运行：

```bash
cd ~/aiot_conductor/project
bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh
```

电脑浏览器打开：

```text
http://192.168.43.221:8787/
```

如果树莓派 IP 改变，在树莓派运行：

```bash
hostname -I
```

然后用新的 IP 替换浏览器地址。

健康检查：

```bash
curl http://127.0.0.1:8787/health
```

正常状态：

- 页面状态显示 `live`；
- 页面左右两列分别显示左手和右手 micro:bit，不会再由最新到达的一侧抢占显示；
- 两列中的 `sequence` 分别持续增长；
- 原始 JSON 中交替出现 `"source":"left"` 和 `"source":"right"`；
- `gateway.flags` 为 `1`，表示数据来自 BLE 广播转发链路；
- `gateway.ble_rssi` 有数值，通常越接近 0 信号越强；
- `sequence_status` 可能出现 `in_order` 或 `sequence_gap`。

后台运行方式：

```bash
cd ~/aiot_conductor/project
nohup bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh > /tmp/microbit_esp32_preview.log 2>&1 &
echo $! > /tmp/microbit_esp32_preview.pid
```

停止后台预览：

```bash
kill $(cat /tmp/microbit_esp32_preview.pid)
```

查看日志：

```bash
tail -f /tmp/microbit_esp32_preview.log
```

如果 8787 端口被占用，可以临时换端口：

```bash
PORT=8788 bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh
```

浏览器打开：

```text
http://192.168.43.221:8788/
```

## 3. micro:bit v2 广播数据

当前 micro:bit 端源码在：

```text
hardware/microbit/microbit_to_pi/main.ts
```

左右手身份由源码常量区分：

```typescript
const HAND = 0  // left
const HAND = 1  // right
```

当前广播参数：

```typescript
const SAMPLE_PERIOD_MS = 150
const SENSOR_REPEAT_TOTAL = 1
const SENSOR_REPEAT_INTERVAL_MS = 50
const AD_TX_POWER_DBM = -12
const BLE_CONNECTABLE = false
const EVENT_REPEAT_TOTAL = 7
const EVENT_REPEAT_INTERVAL_MS = 90
const CONTROL_HOLD_MS = 70
```

micro:bit 通过 `bluetooth.advertiseUidBuffer()` 发出 Eddystone UID 广播。由于广播载荷有限，原始项目协议被压缩成 16 字节。

状态样本依靠 BLE 广播层在广告间隔内自然重复；程序不再额外对同一状态样本调用第二次 `advertiseUidBuffer()`，避免额外调用拉长实际采样间隔。ESP32 收到重复序号后只向树莓派转发第一次成功收到的样本。按键事件比状态样本优先级更高，会重复广播 7 次，并在每次事件广播后短暂保持控制包，降低按键事件被状态包覆盖的概率。

状态广播包：

```text
offset  size  field
0       1     compact_type = 0xa1
1       1     original header, includes HAND
2       2     sample_sequence, uint16 little-endian
4       4     device_timestamp_ms, uint32 little-endian
8       2     ax_mg, int16 little-endian
10      2     ay_mg, int16 little-endian
12      2     az_mg, int16 little-endian
14      1     pitch_deg, int8
15      1     roll_deg, int8
```

控制事件广播包：

```text
offset  size  field
0       1     compact_type = 0xa2
1       1     original header, includes HAND
2       2     event_sequence, uint16 little-endian
4       4     device_timestamp_ms, uint32 little-endian
8       1     event_code
9       1     priority
10      1     repeat_index
11      1     repeat_total
12      4     reserved / guard bytes
```

`az_mg` 表示 micro:bit 加速度计 Z 轴方向的加速度，单位是 mg。静止时某个轴会接近 ±1000 mg，这是重力投影，不是错误。板子平放、正反面和佩戴方向不同，重力会主要落在不同轴上，因此 `az` 的正负要结合实际安装方向解释。

## 4. ESP32 网关处理

ESP32 固件在：

```text
hardware/esp32/microbit_ble_wifi_gateway/MicrobitBleWifiGateway/MicrobitBleWifiGateway.ino
```

ESP32 的职责：

1. 扫描 BLE service UUID `feaa` 的 Eddystone 广播；
2. 解析 16 B 紧凑广播负载；
3. 根据 header 中的 hand 位判断 left/right；
4. 将状态包还原为项目原始 17 B micro:bit packet；
5. 将控制事件还原为项目原始 11 B micro:bit packet；
6. 包装为 `MBGW` UDP 网关帧发给树莓派 `17778` 端口。

UDP 网关帧：

```text
offset  size  field
0       4     magic = "MBGW"
4       1     version = 1
5       1     header_len = 18
6       1     payload_len = 11 or 17
7       1     flags = 1, advertising source
8       4     gateway_sequence, uint32 little-endian
12      4     esp_rx_micros, uint32 little-endian
16      1     conn_index, 0 = left, 1 = right
17      1     BLE RSSI, int8
18      N     restored original micro:bit packet
```

`gateway_sequence` 是 ESP32 转发序号，用于观察网关是否持续发送。它不是 micro:bit 采样序号。真正的传感器采样序号是 `sample_sequence`。

## 5. 树莓派 UDP 接收

Pi 端接收器在：

```text
hardware/raspberry_pi/esp32_ble_gateway_to_Pi
```

直接运行接收器：

```bash
cd ~/aiot_conductor/project/hardware/raspberry_pi/esp32_ble_gateway_to_Pi
source ~/aiot_conductor/project/camera_to_Pi/.venv/bin/activate
python -m esp32_gateway_receiver.app --config config.json --log-level WARNING
```

典型状态输出：

```json
{
  "type": "microbit_sensor_state",
  "source": "left",
  "message_type": 1,
  "hand": 0,
  "sample_sequence": 2527,
  "device_timestamp_ms": 505562,
  "pi_rx_monotonic_ns": 13300310620268,
  "raw": {
    "ax_mg": -16,
    "ay_mg": 248,
    "az_mg": -1016,
    "pitch_deg": 13,
    "roll_deg": 0
  },
  "time_alignment": null,
  "sequence_status": "in_order",
  "missing_sample_count": 0,
  "device_restarted": false,
  "transport": "esp32_udp_gateway",
  "gateway": {
    "source_ip": "192.168.43.73",
    "source_port": 59992,
    "gateway_sequence": 788,
    "esp_rx_micros": 332416224,
    "conn_index": 0,
    "ble_rssi": -59,
    "flags": 1
  }
}
```

核心字段解释：

| 字段 | 含义 | 后续用途 |
| --- | --- | --- |
| `source` | `left` 或 `right` | 区分左右手 |
| `sample_sequence` | micro:bit 采样序号 | 检测丢包、重启 |
| `device_timestamp_ms` | micro:bit 采样时刻 | 与 Pi 时间轴对齐 |
| `pi_rx_monotonic_ns` | Pi 收到 UDP 时刻 | 当前最可靠的统一时间锚点 |
| `raw.ax_mg/ay_mg/az_mg` | 三轴加速度 | 姿态和动作特征 |
| `raw.pitch_deg/roll_deg` | micro:bit 姿态角 | 姿态和动作特征 |
| `sequence_status` | 序号状态 | 标记 `in_order`、`sequence_gap`、`device_restart` |
| `gateway.ble_rssi` | ESP32 收到该广播的信号强度 | 调试距离和干扰 |
| `gateway.flags` | `1` 表示广播来源 | 区分旧 BLE 连接来源 |

控制事件输出应走快速路径，不等待摄像头融合：

```json
{
  "type": "microbit_control_event",
  "source": "right",
  "event_sequence": 215,
  "event_code": "B_LONG_PRESS",
  "priority": 100,
  "duplicate": false,
  "mapped_candidate": "emergency_stop"
}
```

## 6. 摄像头数据输出

摄像头工程在：

```text
hardware/raspberry_pi/camera_to_Pi
```

运行摄像头可视预览：

```bash
cd ~/aiot_conductor/project/hardware/raspberry_pi/camera_to_Pi
source ~/aiot_conductor/project/camera_to_Pi/.venv/bin/activate
python visual_verify.py --config config.json --host 0.0.0.0 --port 8765
```

浏览器打开：

```text
http://192.168.43.221:8765/
```

运行摄像头 JSONL 输出：

```bash
cd ~/aiot_conductor/project/hardware/raspberry_pi/camera_to_Pi
source ~/aiot_conductor/project/camera_to_Pi/.venv/bin/activate
python main.py --config config.json --output /tmp/camera.jsonl
```

摄像头输出类型：

```text
camera_landmark_frame
```

核心字段：

| 字段 | 含义 |
| --- | --- |
| `frame_sequence` | 摄像头输出帧序号 |
| `sensor_timestamp_ns` | libcamera 传感器时间戳 |
| `pi_frame_received_ns` | Python 取到帧时的 Pi 单调时钟 |
| `pi_aligned_timestamp_ns` | 摄像头时间映射到 Pi 时间轴后的结果 |
| `camera.hands_detected` | MediaPipe 原始检测手数 |
| `camera.hands[].hand_label` | `left` 或 `right` |
| `camera.hands[].image_landmarks` | 21 点图像坐标 |
| `camera.hands[].world_landmarks` | 21 点世界坐标 |
| `camera.hands[].detection_valid` | 是否适合进入高质量数据整理 |
| `camera.hands[].quality_score` | 工程质量分 |
| `camera.hands[].quality_flags` | 质量问题标记 |

## 7. 与摄像头数据一同整理

树莓派侧建议使用统一的 Pi 单调时钟作为融合时间轴：

```text
microbit sample time -> pi_aligned_timestamp_ns
camera frame time    -> pi_aligned_timestamp_ns
```

当前摄像头已经输出 `pi_aligned_timestamp_ns`。micro:bit 侧当前最稳妥的初始策略是先使用 `pi_rx_monotonic_ns` 作为融合时间，再逐步加入 `MicrobitClockMapper`。

初始整理流程：

1. 启动 `esp32_gateway_receiver`，接收左右 micro:bit JSONL；
2. 启动 `camera_to_Pi/main.py`，输出摄像头 JSONL；
3. 在同一个树莓派进程内建立三个短窗口缓存：
   - `left_microbit_buffer`
   - `right_microbit_buffer`
   - `camera_frame_buffer`
4. 每来一帧摄像头数据，以 `camera.pi_aligned_timestamp_ns` 为目标时间；
5. 从左右 micro:bit buffer 中选择最接近该时间的样本；
6. 如果 micro:bit 样本距离目标时间小于阈值，例如 `120 ms`，纳入融合帧；
7. 如果超出阈值，标记该侧 `available=false`，不要用旧数据伪装实时数据；
8. 控制事件单独输出，不等待摄像头帧。

推荐初始阈值：

```text
camera_max_age_ms = 120
microbit_max_age_ms = 120
fusion_rate = camera frame rate
interpolation = nearest
```

后续如果需要更平滑，可将 micro:bit 最近邻选择升级为线性插值：

```text
target_time between sample_n and sample_n+1
interpolated_value = value_n + ratio * (value_n+1 - value_n)
```

控制事件不做插值，只按事件时间进入快速控制路径。

## 8. 融合输出建议

融合后继续使用 JSON Lines，每行一个完整对象。建议三类输出：

| type | 说明 |
| --- | --- |
| `fused_frame` | 摄像头帧附近的一组 micro:bit + camera 同步数据 |
| `control_event` | 按钮、急停等低延迟事件 |
| `status` | 链路健康状态 |

`fused_frame` 建议结构：

```json
{
  "type": "fused_frame",
  "schema_version": "1.0",
  "fused_sequence": 1024,
  "pi_aligned_timestamp_ns": 48392020000000,
  "left_microbit": {
    "available": true,
    "sample_sequence": 2527,
    "time_delta_ms": -14.2,
    "ax_mg": -16,
    "ay_mg": 248,
    "az_mg": -1016,
    "pitch_deg": 13,
    "roll_deg": 0,
    "sequence_status": "in_order",
    "missing_sample_count": 0
  },
  "right_microbit": {
    "available": true,
    "sample_sequence": 2463,
    "time_delta_ms": 8.7,
    "ax_mg": -24,
    "ay_mg": 400,
    "az_mg": -936,
    "pitch_deg": 23,
    "roll_deg": -1,
    "sequence_status": "sequence_gap",
    "missing_sample_count": 2
  },
  "camera": {
    "available": true,
    "frame_sequence": 392,
    "time_delta_ms": 0.0,
    "hands_detected": 2,
    "hands": []
  },
  "fusion_quality": {
    "max_time_delta_ms": 14.2,
    "missing_sources": [],
    "camera_quality_flags": [],
    "microbit_quality_flags": ["right_sequence_gap"]
  }
}
```

`status` 建议每 1 秒输出一次：

```json
{
  "type": "status",
  "schema_version": "1.0",
  "pi_timestamp_ns": 48392030000000,
  "microbit": {
    "left_age_ms": 41,
    "right_age_ms": 64,
    "left_rssi": -59,
    "right_rssi": -66,
    "left_missing_sample_count": 0,
    "right_missing_sample_count": 2
  },
  "camera": {
    "fps": 20.0,
    "hands_detected": 2,
    "dropped_capture_frames": 0,
    "clock_ready": true
  }
}
```

## 9. 采集文件方式

如果还没有做融合进程，可以先分别落盘，后续离线对齐：

终端 A，采集 micro:bit：

```bash
cd ~/aiot_conductor/project/hardware/raspberry_pi/esp32_ble_gateway_to_Pi
source ~/aiot_conductor/project/camera_to_Pi/.venv/bin/activate
python -m esp32_gateway_receiver.app --config config.json --log-level WARNING > /tmp/microbit_esp32.jsonl
```

终端 B，采集摄像头：

```bash
cd ~/aiot_conductor/project/hardware/raspberry_pi/camera_to_Pi
source ~/aiot_conductor/project/camera_to_Pi/.venv/bin/activate
python main.py --config config.json --output /tmp/camera.jsonl
```

离线整理时按时间字段排序：

- micro:bit：先用 `pi_rx_monotonic_ns`；
- camera：用 `pi_aligned_timestamp_ns`；
- 后续加入 micro:bit 时钟映射后，再统一改用 micro:bit 的 `pi_aligned_timestamp_ns`。

## 10. 稳定性判断

广播方案的稳定性不要按“是否连接”判断，而按下面指标判断：

- `left` 和 `right` 是否在页面或 JSON 中持续出现；
- 每侧 `age` 是否大部分时间低于 1 秒；
- `gateway_sequence` 是否持续增长；
- `gateway.ble_rssi` 是否长期低于约 `-85 dBm`；
- `sequence_gap` 是否集中爆发，而不是偶发。

如果丢包偏多，按优先级处理：

1. ESP32 与两块 micro:bit 保持 30 cm 到 1 m；
2. 两块 micro:bit 不要贴在一起；
3. ESP32 靠近 Wi-Fi 热点，减少 Wi-Fi 重连；
4. 当前已采用 `SAMPLE_PERIOD_MS = 150`，状态包依靠 BLE 广播层自然重复，程序不做额外状态重复调用；
5. 如果丢包仍偏多，优先观察 RSSI 和摆放，再考虑回退到 200 ms 或改用更可靠的无线节点；
6. 如果后续对丢包零容忍，应改用 ESP-NOW、专用 2.4 GHz 模块，或把 IMU 直接接到 ESP32。
