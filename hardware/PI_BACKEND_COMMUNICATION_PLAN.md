# Raspberry Pi 与 PC 后端通信方案

**日期**: 2026-07-23

本文档说明统一目录整理后的预期通信方式。当前目标是让树莓派在一个运行环境内完成：

```text
micro:bit L/R -> ESP32 -> Raspberry Pi
Pi Camera -> Raspberry Pi
Raspberry Pi fusion_pipeline -> PC backend
PC backend -> 后续模型、Sonic Pi、LED 控制
```

完整端到端操作步骤见：

```text
hardware/END_TO_END_TRANSMISSION_VERIFICATION.md
```

## 1. 运行角色

| 节点 | 职责 | 运行位置 |
| --- | --- | --- |
| micro:bit L/R | BLE 广播 IMU 与按键事件 | `hardware/microbit/microbit_to_pi/` |
| ESP32 | BLE-to-Wi-Fi 网关，扫描 micro:bit 广播并 UDP 转发 | `hardware/esp32/microbit_ble_wifi_gateway/` |
| Raspberry Pi | 接收 ESP32 UDP、采集摄像头、时间对齐、融合输出 | `/home/ag1_client/aiot_conductor/project` |
| PC Backend | TCP JSONL 服务端，接收 Pi 上行数据，提供 REST 状态接口 | `backend/` |

树莓派统一 Python 环境：

```text
/home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv/bin/python
```

## 2. 网络与端口

| 方向 | 协议 | 端口 | 说明 |
| --- | --- | --- | --- |
| ESP32 -> Pi | UDP | `17778` | ESP32 将 micro:bit 广播帧封装为 MBGW 帧后发送给 Pi |
| Pi -> PC Backend | TCP JSON Lines | `9000` | `fusion_pipeline/tcp_client.py` 主动连接 PC 后端 |
| PC REST API | HTTP | `5000` | `backend/app.py` 对外提供状态和调试接口 |
| Pi camera preview | HTTP | `8765` | 仅用于摄像头预览验证，不与 fusion 同时运行 |
| Pi micro:bit preview | HTTP | `8787` | 仅用于 micro:bit 预览验证，不与 fusion 同时运行 |

当前配置：

```yaml
tcp:
  host: "192.168.43.209"
  port: 9000

gateway:
  listen_host: "0.0.0.0"
  listen_port: 17778
```

注意：`pi-fusion.service` 会占用 UDP `17778` 和 Pi Camera。启动 fusion 前应停止摄像头预览和 micro:bit 预览。

## 3. 启动顺序

1. 启动 PC 后端：

```powershell
cd G:\code\AIoT\AIoT
backend\.venv\Scripts\python.exe backend\app.py
```

后端启动后会：

- 监听 HTTP `0.0.0.0:5000`
- 启动 `pi_gateway.py`
- 监听 TCP `0.0.0.0:9000`

2. ESP32 上电并连接 Wi-Fi。

ESP32 需要与 Pi、PC 在同一网络内，并向 Pi 的 `17778` 端口发送 UDP 数据。

3. micro:bit L/R 上电。

两块 micro:bit 使用广播固件，分别显示 `L` / `R`，持续广播传感器样本；按键事件会重复广播，提高事件到达概率。

4. 启动 Pi 融合管线：

```bash
cd /home/ag1_client/aiot_conductor/project/hardware/fusion_pipeline
/home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv/bin/python main.py --config config.yaml
```

或使用 systemd：

```bash
sudo systemctl start pi-fusion
sudo journalctl -u pi-fusion -f
```

## 4. 上行消息

Pi 到 PC 后端使用 TCP JSON Lines：

```text
一行 = 一个 JSON 对象 + "\n"
```

后端入口：

```text
backend/pi_gateway.py
```

后端路由：

```text
backend/message_router.py
```

当前接受三类上行消息：

| type | 触发 | 后端用途 |
| --- | --- | --- |
| `fused_frame` | 摄像头帧驱动，约 15~20 Hz | 更新实时传感器状态、保留融合数据 |
| `control_event` | micro:bit 按键事件 | 更新音乐控制状态，转发 Sonic Pi 控制 |
| `status` | 约 1 Hz | 更新 Pi、camera、micro:bit 链路健康状态 |

## 5. `fused_frame`

`fused_frame` 由摄像头帧触发。Pi 会将摄像头时间戳作为目标时间，在 micro:bit 左右手缓冲区中寻找最近样本。

示例：

```json
{
  "type": "fused_frame",
  "schema_version": "1.0",
  "fused_sequence": 128,
  "pi_aligned_timestamp_ns": 123456789000,
  "camera": {
    "available": true,
    "frame_sequence": 456,
    "time_delta_ms": 0.0,
    "hands_detected": 1,
    "hands": [],
    "detection_quality": {
      "hand_detection_rate_5s": 0.92,
      "consecutive_missed_frames": 0,
      "preview_interpolated_hands": 0
    }
  },
  "microbits": [
    {
      "hand": "left",
      "available": true,
      "sample_sequence": 1001,
      "time_delta_ms": -22.4,
      "ax_mg": 12.0,
      "ay_mg": -18.0,
      "az_mg": 996.0,
      "pitch_deg": 3.0,
      "roll_deg": -2.0,
      "sequence_status": "in_order",
      "missing_sample_count": 0
    },
    {
      "hand": "right",
      "available": false,
      "sample_sequence": 0,
      "time_delta_ms": 180.2,
      "ax_mg": 0,
      "ay_mg": 0,
      "az_mg": 0,
      "pitch_deg": 0,
      "roll_deg": 0,
      "sequence_status": "",
      "missing_sample_count": 0
    }
  ],
  "fusion_quality": {
    "max_time_delta_ms": 22.4,
    "missing_sources": ["right_microbit"],
    "camera_quality_flags": [],
    "microbit_quality_flags": []
  }
}
```

后端会把顶层业务字段自动归入 `payload`，因此上述顶层格式可直接被 `message_router.py` 兼容处理。

## 6. `control_event`

`control_event` 是按键事件快速通道，不等待摄像头帧，也不进入 jitter buffer。

示例：

```json
{
  "type": "control_event",
  "schema_version": "1.0",
  "source": "left",
  "event_sequence": 23,
  "pi_rx_monotonic_ns": 123456789000,
  "payload": {
    "event": {
      "type": "resume",
      "source": "left",
      "code": "A_SHORT_PRESS",
      "candidate": "start_or_resume",
      "priority": 40,
      "repeat_index": 0,
      "repeat_total": 7,
      "strength": 1.0
    },
    "music_control": {},
    "microbit": {
      "source": "left",
      "event_sequence": 23,
      "event_code": "A_SHORT_PRESS",
      "mapped_candidate": "start_or_resume"
    },
    "gateway": {
      "source_ip": "192.168.43.xxx",
      "ble_rssi": -62,
      "flags": 0
    }
  }
}
```

按键语义映射：

| micro:bit 候选语义 | 后端事件 `payload.event.type` | 说明 |
| --- | --- | --- |
| `start_or_resume` | `resume` | 开始或继续 |
| `pause` | `cutoff` | 当前后端将其作为停止类控制处理 |
| `style_switch` | `style_switch` | 风格切换 |
| `emergency_stop` | `stop` | 紧急停止 |
| `recalibrate` | `gesture_start` | 当前作为可识别事件占位，后续可改为专用校准命令 |

## 7. `status`

`status` 每秒发送一次，用于后端页面和调试接口判断链路健康。

示例：

```json
{
  "type": "status",
  "schema_version": "1.0",
  "pi_timestamp_ns": 123456789000,
  "microbits": {
    "left": {
      "connected": true,
      "age_ms": 35.0,
      "rssi": -61,
      "missing_sample_count": 2
    },
    "right": {
      "connected": true,
      "age_ms": 42.0,
      "rssi": -67,
      "missing_sample_count": 5
    }
  },
  "camera": {
    "fps": 18.2,
    "hands_detected": 1,
    "hand_detection_rate_5s": 0.92,
    "consecutive_missed_frames": 0,
    "preview_interpolated_hands": 0,
    "dropped_capture_frames": 0,
    "clock_ready": true,
    "pixel_format": "BGR888",
    "detector": {
      "detection": 0.35,
      "presence": 0.35,
      "tracking": 0.4
    }
  },
  "jitter": {
    "configured_delay_ms": 250.0,
    "pending_frames": 8
  }
}
```

建议后续将 `connected` 改为基于 `age_ms` 计算，例如 `age_ms < 1000` 才认为在线。

## 8. 后端验证接口

PC 后端启动后，可用这些接口检查是否收到 Pi 数据：

```text
GET http://localhost:5000/api/status
GET http://localhost:5000/api/pi/status
GET http://localhost:5000/api/pi/messages?limit=20
GET http://localhost:5000/api/sensors/live
GET http://localhost:5000/api/music/state
```

重点观察：

- `/api/status` 中 `pi_gateway.running` 是否为 `true`
- `/api/status` 中 `pi_gateway.connected` 是否为 `true`
- `/api/pi/status` 中 `message_counts.fused_frame/status/control_event` 是否递增
- `/api/sensors/live` 是否出现左右 micro:bit 和 camera 最新状态

推荐使用 PC 端验证脚本自动观察这些字段：

```powershell
cd G:\code\AIoT\AIoT
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 30
```

## 9. 下行通道预留

PC 后端可以通过同一 TCP 连接向 Pi 发送下行消息，入口是：

```text
POST http://localhost:5000/api/pi/send
```

当前后端允许的下行类型：

```text
led_command
led_state
led_config
system_command
time_sync
```

LED 控制建议使用：

```json
{
  "type": "led_command",
  "payload": {
    "mode": "gesture_feedback",
    "color": [255, 80, 20],
    "brightness": 0.6,
    "duration_ms": 300,
    "source": "backend"
  }
}
```

Pi 侧后续需要在 `fusion_pipeline` 或独立 LED 服务中增加 TCP 下行读取与分发，将 `led_command` 转给：

```text
hardware/raspberry_pi_iot/led/
```

## 10. 常见冲突

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| fusion 启动失败，提示 UDP 地址占用 | micro:bit 预览仍占用 `17778` | 停止 `8787` 预览服务 |
| fusion 启动后没有摄像头 | camera 预览仍占用 Pi Camera | 停止 `8765` 预览服务 |
| 后端 `pi_gateway.connected=false` | PC 后端未启动，或 `tcp.host` 不是 PC 当前 IP | 启动 `backend/app.py`，确认 PC IP |
| `status` 有数据但 `control_event` 不递增 | 按键事件未到达或被去重 | 检查 micro:bit 按键重复广播和 ESP32 日志 |
| `fused_frame` 中某只手经常 `available=false` | micro:bit 样本相对摄像头帧超出 `max_age_ms` | 将 `max_age_ms` 调到 `250-350` 并观察 `time_delta_ms` |
