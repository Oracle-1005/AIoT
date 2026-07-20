# 树莓派 → PC 接口与数据处理规范

> 基于 `raspberry_pi_iot/` 代码实现，版本 schema `1.1`

---

## 目录

1. [总体架构](#1-总体架构)
2. [树莓派 → PC 接口：三类消息](#2-树莓派--pc-接口三类消息)
   - [2.1 公共顶层字段](#21-公共顶层字段)
   - [2.2 fused_frame](#22-fused_frame)
   - [2.3 control_event](#23-control_event)
   - [2.4 status](#24-status)
3. [数据噪声处理](#3-数据噪声处理)
   - [3.1 Micro:bit IMU 噪声过滤](#31-microbit-imu-噪声过滤)
   - [3.2 Camera/MediaPipe 关键点平滑](#32-cameramediapipe-关键点平滑)
   - [3.3 BLE 丢包检测与插值](#33-ble-丢包检测与插值)
4. [时间对齐方式](#4-时间对齐方式)
   - [4.1 BLE 时钟同步](#41-ble-时钟同步)
   - [4.2 BLE → Camera 时间对齐](#42-ble--camera-时间对齐)
   - [4.3 对齐容差与无效判定](#43-对齐容差与无效判定)
5. [数据转换流程](#5-数据转换流程)
   - [5.1 完整处理管道](#51-完整处理管道)
   - [5.2 特征计算](#52-特征计算)
   - [5.3 滑动窗口与事件检测](#53-滑动窗口与事件检测)
6. [配置参数参考](#6-配置参数参考)

---

## 1. 总体架构

```text
左手 micro:bit ─┐
                 ├─ BLE (25Hz, 19字节二进制) ─┐
右手 micro:bit ─┘                             │
                                               ▼
摄像头 ─ CSI/USB (30FPS) ──────────────── 树莓派
                                               │
                              ┌─────────────────┴─────────────────┐
                              │  fused_frame (20-30Hz)            │
                              │  control_event (事件触发)          │
                              │  status (1Hz)                     │
                              │  TCP + JSON Lines :9000           │
                              ▼                                   │
                             PC                                   │
                        ┌─────┼─────┐                             │
                        ▼     ▼     ▼                             │
                     AI推理 音乐控制 数据存储                       │
```

**树莓派内置处理管道：**

```text
BLE Notification (19 bytes)
  │
  ├─→ PacketParser         struct.unpack 二进制解析
  ├─→ MicrobitNoiseFilter  EMA低通 + 中值去尖峰
  ├─→ DataCleaner          序列号间隙检测 + 丢包率统计
  ├─→ ClockSync            device_to_pi_ns() 时钟映射
  │
  ▼
RingBuffer (时间排序环形缓冲, maxlen=500)
  │
  ├─→ TimeAligner          bracket搜索 + 线性插值 → 对齐到Camera时间
  ├─→ FusionEngine         融合 → fused_frame
  │
  ├───→ SlidingWindowComputer (内部, 800ms/100ms)
  │       └──→ 事件检测 (rule-based) → control_event
  │
  └───→ StatusMonitor (1Hz) → status

Camera (30FPS)
  │
  ├─→ Picamera2            原始RGB帧 + SensorTimestamp
  ├─→ MediaPipe            21手部关键点 × 2手
  ├─→ LandmarkSmoother     自适应时间平滑
  ├─→ InstantFeature       wrist_velocity, openness, direction
  │
  ▼
CameraFrame → RingBuffer → FusionEngine
```

---

## 2. 树莓派 → PC 接口：三类消息

**传输方式**：TCP + JSON Lines，树莓派为 Client，PC 为 Server，端口 `9000`。  
每条消息为一个完整 JSON 对象 + `\n` 换行符结束。

### 2.1 公共顶层字段

所有三类消息均包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 数据结构版本，当前 `"1.1"` |
| `message_type` | string | 消息类型：`fused_frame` / `control_event` / `status` |
| `session_id` | string | 一次运行会话的唯一标识，格式 `session-YYYYMMDD-HHMMSS` |
| `packet_sequence` | int | 树莓派全局消息序号，从 1 开始递增，PC 用于检测丢包 |
| `pi_id` | string | 树莓派标识，默认 `"raspberrypi-01"`，支持多 Pi 部署 |
| `timestamps.pi_packet_created_mono_ns` | int | 树莓派创建该消息的单调时钟 (ns)，起点为系统启动 |
| `timestamps.pi_unix_time_ns` | int | Unix 时间戳 (ns)，可用于跨设备比较（需 NTP 同步） |

**代码位置**：`messages/builder.py` → `MessageBuilder._common_fields()`

---

### 2.2 fused_frame

**用途**：以摄像头帧时间为基准，将该时刻的视觉数据和左右 micro:bit 数据同步到同一时间点后生成的一条融合数据。是整个系统中最接近原始数据的一层。

**频率**：20–30 Hz（由摄像头帧率驱动，可配置 `fused_frame_max_hz`）

**完整 JSON 结构**：

```json
{
  "schema_version": "1.1",
  "message_type": "fused_frame",
  "session_id": "session-20260720-143052",
  "packet_sequence": 10248,
  "pi_id": "raspberrypi-01",
  "timestamps": {
    "fusion_target_timestamp_ns": 153482300000000,
    "pi_packet_created_mono_ns": 153482315600000,
    "pi_unix_time_ns": 1783933212345678900
  },
  "camera": {
    "source": "camera",
    "frame_id": 4821,
    "sensor_timestamp_ns": 153482300000000,
    "mediapipe_timestamp_ms": 153482300,
    "width": 640,
    "height": 480,
    "configured_fps": 30,
    "processing_latency_ms": 12.4,
    "hands": [
      {
        "hand_id": "left-0",
        "handedness": "left",
        "confidence": 0.97,
        "valid": true,
        "landmarks_normalized": [[0.514, 0.742, -0.012], "… 21个关键点"],
        "world_landmarks": [],
        "features": {
          "palm_center": [0.507, 0.613, -0.019],
          "palm_normal": [0.0, 0.0, 1.0],
          "openness": 0.78,
          "finger_states": [1, 1, 1, 1, 1],
          "joint_angles": [],
          "pinch_distance": 0.05,
          "wrist_position": [0.514, 0.742, -0.012],
          "wrist_velocity": [0.18, -0.43, 0.02],
          "wrist_acceleration": [0.0, 0.0, 0.0],
          "motion_direction": "up"
        }
      }
    ]
  },
  "microbits": [
    {
      "source": "microbit_ble",
      "device_id": "MB_LEFT",
      "hand": "left",
      "ble_address": "AA:BB:CC:DD:EE:01",
      "valid": true,
      "timestamps": {
        "device_timestamp_ms": 192640,
        "pi_receive_timestamp_ns": 153482304800000,
        "pi_aligned_timestamp_ns": 153482300000000
      },
      "raw_interpolated": {
        "acceleration_mg": [84, 1164, -362],
        "pitch_deg": 18,
        "roll_deg": -7
      },
      "instant_features": {
        "acceleration_g": [0.084, 1.164, -0.362],
        "acceleration_magnitude_g": 1.221,
        "linear_acceleration_g": [0.061, 0.294, -0.105],
        "linear_acceleration_magnitude_g": 0.312,
        "jerk_g_s": [2.32, 0.0, 1.24],
        "jerk_magnitude_g_s": 2.63,
        "motion_energy": 0.052
      },
      "ble": {
        "rssi_dbm": -58,
        "notification_sequence": 9632,
        "recent_loss_ratio": 0.01,
        "connection_interval_ms": 30
      },
      "sync": {
        "method": "ble_clock_mapping_and_interpolation",
        "nearest_sample_error_ms": 7.5,
        "bracket_span_ms": 38.4,
        "sync_rtt_ms": 11.2,
        "clock_ready": true
      }
    }
  ],
  "fusion": {
    "valid": true,
    "alignment_method": "camera_timestamp_target",
    "camera_valid": true,
    "left_microbit_valid": true,
    "right_microbit_valid": true,
    "cross_modal_features": {
      "beat_candidate": false,
      "beat_strength": 0.0,
      "vision_imu_consistency": 0.0,
      "combined_motion_intensity": 0.0
    }
  }
}
```

**字段说明**：

| 字段路径 | 来源 | 说明 |
|----------|------|------|
| `timestamps.fusion_target_timestamp_ns` | 摄像头 `SensorTimestamp` | **融合时间基准**，所有 micro:bit 数据插值到此时刻 |
| `camera.frame_id` | `_frame_counter` | 摄像头帧序号，递增 |
| `camera.sensor_timestamp_ns` | Picamera2 元数据 | 传感器产生该帧的时刻 |
| `camera.hands[]` | MediaPipe + `_extract_hand_data()` | 每只检测到的手一个对象 |
| `camera.hands[].landmarks_normalized` | 经 `LandmarkSmoother` 平滑 | 21 个归一化关键点 `[x, y, z]`，已做自适应时间平滑 |
| `camera.hands[].features.wrist_velocity` | `_compute_camera_features()` | 手腕归一化坐标的速度 `[dx/dt, dy/dt, dz/dt]` |
| `camera.hands[].features.openness` | `_compute_openness()` | 掌张开程度 `[0, 1]`，指尖到腕距 ÷ MCP到腕距 |
| `camera.hands[].features.motion_direction` | 速度向量方向离散化 | `up/down/left/right/forward/backward/still` |
| `microbits[].raw_interpolated` | `TimeAligner._linear_interpolate()` | 插值到 `fusion_target` 的原始传感器值，**已做噪声过滤** |
| `microbits[].instant_features` | `InstantFeatureComputer` | 从插值后数据计算的逐帧特征 |
| `microbits[].sync.nearest_sample_error_ms` | `TimeAligner.align()` | 融合目标时间与最近样本的时间差，越小越好 |
| `microbits[].sync.bracket_span_ms` | `TimeAligner.align()` | 插值前后两个样本的时间跨度 |
| `fusion.valid` | `FusionEngine._fuse()` | 摄像头有效 **且** 至少一侧 micro:bit 有效 |

**代码位置**：`fusion/engine.py` → `FusionEngine._fuse()` 生成 dict，`messages/builder.py` → `MessageBuilder.build_fused_frame()` 添加公共字段。

---

### 2.3 control_event

**用途**：已确认的离散动作事件或控制事件。经过滑动窗口统计、阈值判断、规则引擎处理后生成，PC 用于驱动音乐和 LED。

**频率**：事件触发（非固定频率），有冷却时间保护（默认 200ms）。

**JSON 结构**：

```json
{
  "schema_version": "1.1",
  "message_type": "control_event",
  "session_id": "session-20260720-143052",
  "packet_sequence": 10401,
  "pi_id": "raspberrypi-01",
  "timestamps": {
    "pi_packet_created_mono_ns": 153482315600000,
    "pi_unix_time_ns": 1783933212345678900
  },
  "event_id": "evt-00001",
  "event": {
    "type": "right_wrist_strike",
    "hand": "right",
    "confidence": 0.94,
    "strength": 0.83
  },
  "music_control": {
    "estimated_bpm": 118.1,
    "tempo_delta": 0.0,
    "volume": 0.66,
    "intensity": 0.83,
    "articulation": 0.5
  },
  "led_control": {
    "pattern": "right_pulse",
    "brightness": 0.42,
    "duration_ms": 120
  }
}
```

**事件类型枚举**（`messages/schemas.py` → `EVENT_TYPES`）：

| 类型 | 含义 |
|------|------|
| `downbeat` | 通用节拍（强度较低） |
| `left_wrist_strike` | 左手腕击拍（强度 > 0.7） |
| `right_wrist_strike` | 右手腕击拍（强度 > 0.7） |
| `bilateral_strike` | 双手同步击拍 |
| `gesture_start` | 手势开始（预留） |
| `gesture_end` | 手势结束（预留） |
| `stop` | 停止（预留） |
| `resume` | 恢复（预留） |

**事件检测逻辑**（`main.py` → `AppController._detect_event_from_window()`）：

1. 800ms 滑动窗口计算 `window_features`（内部，不发 PC）
2. 取左右手 `max_jerk_g_s` 的最大值
3. 超过阈值 `jerk_threshold_g_s`（默认 5.0 g/s）→ 触发事件
4. 强度 > 0.7 → `{hand}_wrist_strike`，否则 `downbeat`
5. 强度映射到 music_control（volume = strength × 0.8）和 led_control（brightness = strength × 0.5）

**代码位置**：`main.py` → `_detect_event_from_window()`，`messages/builder.py` → `build_control_event()`

---

### 2.4 status

**用途**：系统健康状态监控。不描述用户动作，仅报告各子系统是否正常工作。

**频率**：1 Hz（可配置 `status_interval_s`）

**JSON 结构**：

```json
{
  "schema_version": "1.1",
  "message_type": "status",
  "session_id": "session-20260720-143052",
  "packet_sequence": 10402,
  "pi_id": "raspberrypi-01",
  "timestamps": {
    "pi_packet_created_mono_ns": 153482415600000,
    "pi_unix_time_ns": 1783933222345678900
  },
  "camera": {
    "connected": true,
    "configured_fps": 30,
    "actual_fps": 29.4,
    "dropped_frames": 3,
    "last_frame_age_ms": 18.2,
    "processing_latency_ms": 12.4
  },
  "microbits": {
    "left": {
      "device_id": "MB_LEFT",
      "transport": "ble",
      "connected": true,
      "rssi_dbm": -58,
      "sample_rate_hz": 24.8,
      "recent_loss_ratio": 0.01,
      "clock_ready": true,
      "sync_rtt_ms": 11.2,
      "last_sample_age_ms": 28.5
    },
    "right": {
      "device_id": "MB_RIGHT",
      "transport": "ble",
      "connected": true,
      "rssi_dbm": -61,
      "sample_rate_hz": 24.6,
      "recent_loss_ratio": 0.02,
      "clock_ready": true,
      "sync_rtt_ms": 13.1,
      "last_sample_age_ms": 32.0
    }
  },
  "network": {
    "pc_connected": true,
    "queued_messages": 2,
    "dropped_messages": 0,
    "send_rate_hz": 36.4,
    "reconnect_count": 1
  },
  "led": {
    "connected": true,
    "backend": "rpi_ws281x",
    "gpio": 18,
    "panel_count": 2,
    "total_leds": 512,
    "brightness_limit": 0.25,
    "actual_brightness": 0.18,
    "fps": 50,
    "error": null
  }
}
```

**代码位置**：`main.py` → `AppController._build_status()` 聚合各子系统状态，`messages/builder.py` → `build_status()`

---

## 3. 数据噪声处理

噪声处理在数据到达后**立即**执行，入口在 `sensors/microbit.py` 的 `handle_raw_packet()` 和 `sensors/camera.py` 的 `_extract_hand_data()`。

### 3.1 Micro:bit IMU 噪声过滤

**代码位置**：`fusion/noise_filter.py` → `MicrobitNoiseFilter`

**处理管道**：

```text
Raw BLE bytes
  → PacketParser.parse()          解析为 ParsedPacket
  → MicrobitNoiseFilter.filter()  噪声过滤 ★
  → DataCleaner.check_sample()    丢包检测
  → ClockSync.device_to_pi_ns()   时钟映射
  → RingBuffer
```

**滤波器组合**：

| 步骤 | 滤波器 | 参数 | 作用 |
|------|--------|------|------|
| 1 | `MedianFilter` (窗口=5) | 对过去5个样本取中值 | 孤立尖峰检测基准 |
| 2 | 尖峰判定 | 阈值 = `outlier_threshold_mg` (默认 500 mg) | 当前值与中值偏差 > 阈值 → 判定为尖峰 |
| 3 | `EMAFilter` (α=0.85 加速度, α=0.90 姿态) | y[n] = 0.85·y[n-1] + 0.15·x[n] | 低通平滑，减少高频振动 |
| 4 | 尖峰替换 | 若检测到尖峰 → 用中值替代原始值再送入 EMA | 避免尖峰污染滤波器状态 |

**EMA 公式**：

```
y[n] = α · y[n-1] + (1 - α) · x[n]

α = 0.85  →  有效窗口 ≈ 1/(1-α) = 6.7 样本 (~270ms @ 25Hz)
α = 0.90  →  有效窗口 ≈ 10 样本 (~400ms @ 25Hz)（用于姿态角）
```

**受过滤的字段**：`ax_mg`, `ay_mg`, `az_mg`, `pitch_deg`, `roll_deg`  
**输出**：`FilteredIMUData`，包含过滤后值 + `outlier_detected` 标志 + `acceleration_magnitude_mg`

**代码位置**：`fusion/noise_filter.py` → `MicrobitNoiseFilter.filter()`

---

### 3.2 Camera/MediaPipe 关键点平滑

**代码位置**：`fusion/noise_filter.py` → `LandmarkSmoother`，调用入口在 `sensors/camera.py` → `_extract_hand_data()`

**滤波器**：`AdaptiveSmoother`（One-Euro-Filter 风格的自适应时间平滑）

**核心公式**：

```text
derivative[n] = β · (value[n] - value[n-1]) / dt  +  (1-β) · derivative[n-1]
speed         = |derivative[n]|
cutoff        = min_cutoff_hz + speed_coefficient · speed
α             = 1 / (1 + 2π · cutoff · dt)
y[n]          = α · value[n] + (1-α) · y[n-1]
```

**关键特性**：
- **低速/静止时**：cutoff ≈ 1.5 Hz，强平滑，消除 jitter
- **快速运动时**：cutoff 自适应升高，减少平滑，保留响应速度
- 21 个关键点 × 3 个坐标轴 = 63 个独立 smoother 实例（每只手）

**参数**：
| 参数 | 默认值 | 含义 |
|------|--------|------|
| `min_cutoff_hz` | 1.5 | 最小截止频率 |
| `beta` | 0.05 | 导数平滑系数 |

**代码位置**：`fusion/noise_filter.py` → `AdaptiveSmoother.update()`、`LandmarkSmoother.smooth_landmarks()`

---

### 3.3 BLE 丢包检测与插值

**代码位置**：`fusion/cleaner.py` → `DataCleaner`

**并非传感器噪声**，而是 BLE 传输层的数据完整性保障。

**检测逻辑**：

```text
收到 sequence → expected = (last_seq + 1) & 0xFFFF
  ├── sequence == expected       → 正常，无丢包
  ├── gap = (seq - expected) & 0xFFFF
  │   ├── gap > 32768            → 回绕/复位，不视为丢包
  │   ├── gap ≤ 32768            → 丢失 gap 个包
  │   │   ├── gap ≤ 3            → 线性插值补齐 (DataCleaner.interpolate_gap)
  │   │   └── gap > 3            → 标记为数据丢失 (fusion valid=false)
  │   └── 更新 loss_history (滑动窗口 100 样本)
  └── 更新 last_seq = sequence
```

**插值字段**：`ax_mg`, `ay_mg`, `az_mg`, `pitch_deg`, `roll_deg`, `device_timestamp_ms`, `pi_aligned_timestamp_ns`

**插值公式**：

```
interpolated[k] = sample_before + (k / total_steps) × (sample_after - sample_before)
```

**丢包率统计**（`recent_loss_ratio`）：
- 窗口大小 = `loss_window_size`（默认 100 个序列事件）
- 比例 = 窗口中丢失数 ÷ 窗口大小
- 发送在 `fused_frame.microbits[].ble.recent_loss_ratio` 和 `status.microbits.*.recent_loss_ratio`

---

## 4. 时间对齐方式

### 4.1 BLE 时钟同步

**代码位置**：`ble/clock_sync.py` → `ClockSync`

Micro:bit 的 `input.runningTime()` 和树莓派的 `time.monotonic_ns()` 使用不同的时钟源，需要通过 SYNC/SYNC_ACK 协议建立线性映射。

**同步协议**：

```text
树莓派                          micro:bit
  │                                │
  ├─ SYNC,<id> ──────────────────→│  t0 = time.monotonic_ns()
  │                                │  m1 = input.runningTime()
  │←─ SYNC_ACK,<id>,<m1> ────────┤  t2 = time.monotonic_ns()
  │                                │
  │  pi_mid = (t0 + t2) / 2       │
  │  rtt    = (t2 - t0) / 1e6 ms  │
```

**线性拟合**：

```
收集 N 个 SyncPoint(t0, device_ms, t2) → 保留 RTT 最小的点
  → numpy.polyfit(device_ms × 1e6, pi_mid_ns, degree=1)
  → pi_ns = a × (device_ms × 1,000,000) + b
```

**异常值剔除**：
- 条件：`RTT > outlier_rtt_factor × median(RTT)`（默认 2.0 倍中位数）
- 保留点数：`min_sync_points` 到 `max_sync_points`（默认 5–20 个）

**同步时机**：
| 阶段 | 行为 |
|------|------|
| 启动 | 连续 15 轮 SYNC，保留最佳 5 个点后 `clock_ready = true` |
| 运行中 | 每 15 秒一次 re-sync，持续更新拟合参数 |
| BLE 重连后 | `ClockSync.reset()` 清空所有点，重新同步 |

**预同步数据缓存**：`clock_ready = false` 期间收到的 BLE 样本暂存在 `MicrobitSensor._pre_sync_cache`（maxlen=500），待时钟就绪后通过 `_flush_pre_sync_cache()` 批量处理。

---

### 4.2 BLE → Camera 时间对齐

**代码位置**：`fusion/aligner.py` → `TimeAligner.align()`

以摄像头 `SensorTimestamp` 为融合目标时间，将 micro:bit 数据插值到此时间点。

**算法流程**：

```text
1. RingBuffer.get_bracket(target_ns, device_id)
   → 在时间排序缓冲中找到 t0 (≤ target) 和 t1 (≥ target)
   → 若 target 超出最新样本，回退到最近两个样本（外推模式）

2. 校验：
   ├── bracket_span_ms > max_bracket_span_ms (100ms) → invalid + "bracket_too_wide"
   ├── sample_age_ms > max_sample_age_ms (120ms)      → invalid + "ble_sample_too_old"
   ├── clock_ready == false                           → invalid + "clock_not_ready"
   └── 无 t0 或 t1                                    → invalid + "no_bracket"

3. 线性插值（5 个字段）：
   ratio = (target_ns - t0_ns) / (t1_ns - t0_ns)
   x(target) = x0 + ratio × (x1 - x0)
```

**外推回退**（`ring_buffer.py` → `get_bracket()` 末尾）：

```text
当 t1_sample 为 None（所有 BLE 样本都在 target 之前）：
  → 使用最近两个样本 (matching[-2], matching[-1]) 作为 bracket
  → 允许短时间外推，避免因微小时间差导致融合失效
```

---

### 4.3 对齐容差与无效判定

| 参数 | 默认值 | 含义 | 代码位置 |
|------|--------|------|----------|
| `max_bracket_span_ms` | 100 ms | 括号跨度超过此值 → 无效 | `aligner.py:77` |
| `max_sample_age_ms` | 120 ms | 最近样本年龄超过此值 → 无效 | `aligner.py:86` |
| `timestamp_alignment_tolerance_ms` | 50 ms | 同步误差阈值（用于日志，非硬拒绝） | `aligner.py:95` |
| `buffer_max_age_s` | 10 s | 环形缓冲最大样本年龄 | `ring_buffer.py:40` |

---

## 5. 数据转换流程

### 5.1 完整处理管道

```text
═══════════════════════════════════════════════════════════════
  BLE 数据路径 (micro:bit → fused_frame)
═══════════════════════════════════════════════════════════════

Step 1  BLE Notification 到达
         → BleManager._make_notify_handler()
         → 记录 pi_receive_timestamp_ns
         文件: ble/ble_manager.py:219

Step 2  二进制解析
         → PacketParser.parse()  struct.unpack('<BBH I hhh hh B')
         → 输出: ParsedPacket (device_id, hand, sequence, ax_mg, …)
         文件: ble/packet_parser.py:55

Step 3  噪声过滤 ★
         → MicrobitNoiseFilter.filter()
           ├── MedianFilter 去尖峰 (窗口=5, 阈值=500mg)
           ├── 尖峰替换
           └── EMAFilter 低通 (α=0.85 accel, α=0.90 orientation)
         → 输出: FilteredIMUData (平滑后的 ax/ay/az/pitch/roll)
         文件: fusion/noise_filter.py:253

Step 4  丢包检测
         → DataCleaner.check_sample()
         → 序列号间隙分析 + 丢包率滑动窗口
         → 输出: LossReport (如有丢包)
         文件: fusion/cleaner.py:58

Step 5  时钟映射
         → ClockSync.device_to_pi_ns()
         → device_ms → pi_monotonic_ns
         文件: ble/clock_sync.py:109

Step 6  环形缓冲
         → RingBuffer.push(TimestampedSample)
         → 时间排序插入 (O(1) 追加，O(N) 乱序回退)
         文件: fusion/ring_buffer.py:50

Step 7  时间对齐 (当 Camera 帧到达时触发)
         → TimeAligner.align()
         → bracket搜索 + 线性插值
         → 输出: AlignResult (valid, interpolated, errors)
         文件: fusion/aligner.py:46

Step 8  融合
         → FusionEngine._fuse()
         → 组装 fused_frame dict
         文件: fusion/engine.py:113

Step 9  特征计算
         → InstantFeatureComputer.compute_microbit_features()
         → accel_g, magnitude, linear_accel, jerk, motion_energy
         文件: features/instant.py:36

Step 10 消息构建
         → MessageBuilder.build_fused_frame()
         → 添加 session_id, packet_sequence, unix timestamps
         文件: messages/builder.py:42

Step 11 TCP 发送
         → TcpJsonlClient.send()
         → asyncio.Queue → StreamWriter
         文件: transport/tcp_client.py:102

═══════════════════════════════════════════════════════════════
  Camera 数据路径 (camera → fused_frame)
═══════════════════════════════════════════════════════════════

Step 1  后台线程 _capture_loop()
         → Picamera2.capture_array("main") → RGB array
         → Picamera2.capture_metadata() → SensorTimestamp
         文件: sensors/camera.py:184

Step 2  MediaPipe 推理
         → HandLandmarker.detect_for_video()
         → 输出: 21 landmarks × 2 hands
         文件: sensors/camera.py:198

Step 3  关键点平滑 ★
         → LandmarkSmoother.smooth_landmarks()
         → AdaptiveSmoother (63 个独立 smoother 实例)
         → 输出: 平滑后的 landmarks_normalized
         文件: sensors/camera.py:340

Step 4  视觉特征计算
         → _compute_camera_features()
         → palm_center, openness, wrist_velocity, finger_states, direction
         文件: sensors/camera.py:373

Step 5  CameraFrame → queue.Queue → FusionEngine.on_camera_frame()
         → 触发融合 (BLE Step 7–11)
         文件: fusion/engine.py:80

═══════════════════════════════════════════════════════════════
  事件检测路径 (internal → control_event)
═══════════════════════════════════════════════════════════════

Step 1  fused_frame → SlidingWindowComputer.add_frame()
         → 窗口 800ms / 步长 100ms
         → 统计: RMS/max/mean/std, peaks, BPM, correlation
         文件: features/window.py:68

Step 2  窗口满 → _detect_event_from_window()
         → jerk 阈值比较 (max_jerk_g_s > 5.0)
         → 事件类型判定 (strength > 0.7 → wrist_strike)
         → 生成 event_id + music_control + led_control
         文件: main.py:416

Step 3  MessageBuilder.build_control_event() → TcpJsonlClient.send()
```

---

### 5.2 特征计算

**代码位置**：`features/instant.py` → `InstantFeatureComputer`

**从 micro:bit 原始数据计算的逐帧特征**：

| 特征 | 公式 | 说明 |
|------|------|------|
| `acceleration_g` | `[ax, ay, az] / 1000` | 加速度从 milli-g 转为 g |
| `acceleration_magnitude_g` | `√(ax² + ay² + az²)` | 合加速度，静止≈1g |
| `linear_acceleration_g` | `raw - gravity_estimate` | 去除重力分量，反映真实运动 |
| `linear_acceleration_magnitude_g` | `√(lx² + ly² + lz²)` | 线性运动强度 |
| `jerk_g_s` | `(a[n] - a[n-1]) / Δt` | 加速度变化率，对突发动作敏感 |
| `jerk_magnitude_g_s` | `√(jx² + jy² + jz²)` | Jerk 的模 |
| `motion_energy` | `Σ(linear_accel²)` | 运动能量估计 |

**重力估计**：通过 EMA 低通滤波（α=0.9）从原始加速度中分离重力分量。低频部分 → 重力，高频部分 → 线性运动。

**从 Camera 关键点计算的视觉特征**（`sensors/camera.py` → `_compute_camera_features()`）：

| 特征 | 方法 | 说明 |
|------|------|------|
| `palm_center` | 腕+MCP 关节均值 | 手掌中心位置 |
| `openness` | (指尖距腕 ÷ MCP距腕) 归一化 | 0=握拳，1=张开 |
| `finger_states` | TIP距 > PIP距×1.1 → 伸展 | `[拇指,食指,中指,无名指,小指]` |
| `pinch_distance` | 拇指尖⇔食指尖欧氏距离 | 捏合检测 |
| `wrist_velocity` | `(pos[n]-pos[n-1]) / Δt` | 手腕速度 |
| `motion_direction` | 速度分量最大轴方向 | `up/down/left/right/forward/backward/still` |

---

### 5.3 滑动窗口与事件检测

**代码位置**：`features/window.py` → `SlidingWindowComputer`

窗口统计**仅供内部使用**（不发 PC），用于：

| 统计项 | 方法 | 用途 |
|--------|------|------|
| 合加速度均值/标准差/最大值 | `mean/std/max(acceleration_magnitude_g)` | 运动强度评估 |
| 线性加速度 RMS | `√(Σl²/N)` | 整体动作能量 |
| Jerk 最大/均值 | `max/mean(jerk_magnitude_g_s)` | **主要事件触发信号** |
| 峰值计数 + 时间戳 | 局部最大值检测 | BPM 估计 |
| 运动能量 | `Σ(motion_energy × dt)` | LED 亮度映射 |
| Pitch/Roll 均值/标准差 | `mean/std` | 手腕姿态统计 |
| 视觉-IMU 相关性 | `pearson_r(vision_speed, imu_accel)` | 跨模态一致性校验 |
| BPM 估计 | `60000 / mean(peak_interval_ms)` | 节拍速度 |

**事件触发规则**（`main.py` → `_detect_event_from_window()`）：

```text
if max(left.max_jerk_g_s, right.max_jerk_g_s) > jerk_threshold_g_s (5.0):
    hand     = argmax(left_jerk, right_jerk)
    strength = min(max_jerk / (threshold × 2), 1.0)
    type     = strength > 0.7 ? "{hand}_wrist_strike" : "downbeat"

    volume     = strength × 0.8
    intensity  = strength
    led_brightness = strength × 0.5
    led_pattern    = "{hand}_pulse"
```

---

## 6. 配置参数参考

**完整配置文件**：`config.yaml`

```yaml
# === 噪声过滤参数 ===
fusion:
  noise_filter:
    ema_alpha_accel: 0.85          # 加速度 EMA 系数 [0,1]，越高越平滑
    ema_alpha_orientation: 0.90    # 姿态角 EMA 系数
    median_window: 5               # 中值滤波窗口（奇数）
    outlier_threshold_mg: 500.0    # 尖峰判定阈值 (milli-g)

  # === 时间对齐参数 ===
  max_bracket_span_ms: 100         # 最大插值括号跨度 (ms)
  max_sample_age_ms: 120           # 最大样本年龄 (ms)
  timestamp_alignment_tolerance_ms: 50  # 同步误差容忍 (ms)
  buffer_max_age_s: 10.0           # 环形缓冲最大样本年龄 (s)

  # === BLE 时钟同步参数 ===
  min_sync_points: 5               # 最少同步点数
  max_sync_points: 20              # 最多保留同步点数
  initial_sync_rounds: 15          # 启动时同步轮数
  resync_interval_s: 15            # 运行中重同步间隔 (s)
  sync_outlier_rtt_factor: 2.0     # RTT > 此倍数 × 中位数 = 异常值

  # === 丢包检测参数 ===
  loss_window_size: 100            # 丢包率滑动窗口大小
  max_gap_interpolate: 3           # 最大连续丢包插值数

  # === 事件检测参数 ===
  event_cooldown_ms: 200           # 事件冷却时间 (ms)
  jerk_threshold_g_s: 5.0          # Jerk 触发阈值 (g/s)
  bpm_min: 60                      # 合理 BPM 下限
  bpm_max: 200                     # 合理 BPM 上限

# === 传输参数 ===
pi_to_pc:
  host: "192.168.1.100"            # PC IP
  port: 9000                       # TCP 端口
  fused_frame_max_hz: 25           # fused_frame 发送频率上限
  status_hz: 1                     # status 频率
  max_queue_size: 500              # 发送队列最大容量
  reconnect_delay_s: 2.0           # TCP 重连初始延迟
```

---

## 附录：模块索引

| 模块 | 文件 | 核心职责 |
|------|------|----------|
| `PacketParser` | `ble/packet_parser.py` | 19 字节二进制 → `ParsedPacket` |
| `BleManager` | `ble/ble_manager.py` | 多设备 BLE 连接 + 自动重连 |
| `ClockSync` | `ble/clock_sync.py` | BLE 时钟映射 (SYNC/SYNC_ACK + polyfit) |
| `MicrobitSensor` | `sensors/microbit.py` | BLE 传感器完整生命周期 |
| `CameraSensor` | `sensors/camera.py` | Picamera2 + MediaPipe + 线程 |
| `MicrobitNoiseFilter` | `fusion/noise_filter.py` | IMU EMA + 中值去尖峰 |
| `LandmarkSmoother` | `fusion/noise_filter.py` | MediaPipe 自适应关键点平滑 |
| `DataCleaner` | `fusion/cleaner.py` | 序列号间隙检测 + 线性插值 |
| `RingBuffer` | `fusion/ring_buffer.py` | 时间排序环形缓冲 |
| `TimeAligner` | `fusion/aligner.py` | BLE → Camera 括号插值对齐 |
| `FusionEngine` | `fusion/engine.py` | 多传感器融合编排 |
| `InstantFeatureComputer` | `features/instant.py` | 逐帧加速度/jerk/能量特征 |
| `SlidingWindowComputer` | `features/window.py` | 800ms 滑动窗口统计（内部） |
| `MessageBuilder` | `messages/builder.py` | 3 种消息 JSON 构造 |
| `TcpJsonlClient` | `transport/tcp_client.py` | TCP JSON Lines + 自动重连 |
| `LedController` | `led/controller.py` | WS2812B LED 动画 |
| `AppController` | `main.py` | 顶层编排 + 事件检测 |
