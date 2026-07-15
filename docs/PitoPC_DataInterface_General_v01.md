# 树莓派 → PC 接口数据结构与时间同步实现说明（重构版）

## 1. 文档目的

本文档按“消息层级—完整示例—字段说明—内部生成流程—时间戳同步”的顺序，重新梳理树莓派向 PC 发送的数据。

系统中共有四类消息：

| 消息类型 | 表示内容 | 推荐频率 | PC 端用途 |
|---|---|---:|---|
| `fused_frame` | 同一时刻的摄像头、左手 micro:bit、右手 micro:bit 及即时融合结果 | 20～30 Hz | 实时显示、原始数据保存、调试 |
| `window_features` | 最近一个滑动窗口内的动态统计特征 | 5～10 Hz | 动态手势、BPM、AI 模型输入 |
| `control_event` | 已经确认的动作与音乐控制事件 | 事件触发 | 音乐和界面控制 |
| `status` | 摄像头、BLE、同步、网络和 LED 的运行状态 | 1 Hz | 状态面板、故障诊断 |

四类消息的层级关系：

```text
摄像头帧 + 双 micro:bit BLE 样本
                │
                ▼
          fused_frame
                │
                ▼
       window_features
                │
                ▼
         control_event

status 独立反映系统健康状态
```

---

## 2. 传输协议

推荐使用：

```text
TCP + JSON Lines
```

规则：

- PC 为 TCP Server；
- 树莓派为 TCP Client；
- 每条消息是一个完整 JSON；
- 每条消息以 `\n` 结束；
- 推荐端口：`9000`。

示例：

```text
{"message_type":"fused_frame",...}\n
{"message_type":"window_features",...}\n
{"message_type":"control_event",...}\n
{"message_type":"status",...}\n
```

---

## 3. 公共顶层字段

所有消息都包含以下字段：

```json
{
  "schema_version": "1.1",
  "message_type": "fused_frame",
  "session_id": "session-20260715-001",
  "packet_sequence": 10248,
  "pi_id": "raspberrypi-01",
  "timestamps": {
    "pi_packet_created_mono_ns": 153482315600000,
    "pi_unix_time_ns": 1783933212345678900
  }
}
```

| 字段 | 作用 |
|---|---|
| `schema_version` | 接口版本，便于后续兼容 |
| `message_type` | 消息类型 |
| `session_id` | 一次系统运行的唯一标识 |
| `packet_sequence` | 树莓派发送消息的全局序号 |
| `pi_id` | 树莓派节点 ID |
| `pi_packet_created_mono_ns` | 树莓派创建消息时的单调时间 |
| `pi_unix_time_ns` | 树莓派创建消息时的真实日期时间 |

不同序号不能混用：

```text
packet_sequence       树莓派 → PC 消息序号
camera.frame_id       摄像头帧序号
microbits[].sequence  BLE 样本序号
window.window_id      滑动窗口序号
event.event_id        控制事件 ID
```


---

# 4. `fused_frame`

## 4.1 作用

`fused_frame` 表示：

> 以一个摄像头帧的时间为基准，将该时刻的视觉结果、左手 micro:bit 数据和右手 micro:bit 数据对齐后形成的单帧融合数据。

它是最接近原始采集数据的一层。

## 4.2 包含关系

```text
fused_frame
├── 公共字段
├── timestamps
├── camera
│   └── hands[]
├── microbits[]
│   ├── 左手
│   └── 右手
└── fusion
```

## 4.3 完整 JSON 示例

```json
{
  "schema_version": "1.1",
  "message_type": "fused_frame",
  "session_id": "session-20260715-001",
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
    "configured_fps": 30,
    "actual_fps": 29.4,
    "width": 640,
    "height": 480,
    "exposure_time_us": 8200,
    "processing_latency_ms": 12.4,
    "valid": true,

    "hands": [
      {
        "hand_id": "left-0",
        "handedness": "left",
        "confidence": 0.97,
        "valid": true,
        "landmark_count": 21,
        "landmarks_normalized": [
          [0.412,0.731,-0.018],[0.381,0.684,-0.026],[0.356,0.631,-0.032],
          [0.337,0.579,-0.036],[0.324,0.531,-0.039],[0.417,0.603,-0.025],
          [0.406,0.523,-0.032],[0.398,0.461,-0.037],[0.392,0.409,-0.041],
          [0.452,0.593,-0.024],[0.451,0.503,-0.031],[0.451,0.435,-0.036],
          [0.450,0.380,-0.040],[0.484,0.604,-0.023],[0.492,0.524,-0.030],
          [0.498,0.465,-0.035],[0.503,0.416,-0.038],[0.514,0.626,-0.021],
          [0.531,0.560,-0.028],[0.542,0.511,-0.032],[0.550,0.471,-0.035]
        ],
        "features": {
          "wrist_position": [0.412,0.731,-0.018],
          "palm_center": [0.456,0.609,-0.023],
          "palm_normal": [0.082,-0.913,0.399],
          "openness": 0.86,
          "finger_states": [1,1,1,1,1],
          "pinch_distance": 0.186,
          "wrist_velocity": [0.102,-0.281,0.011],
          "wrist_acceleration": [0.384,-0.712,0.036],
          "motion_direction": "down"
        }
      },
      {
        "hand_id": "right-0",
        "handedness": "right",
        "confidence": 0.95,
        "valid": true,
        "landmark_count": 21,
        "landmarks_normalized": [
          [0.622,0.724,-0.016],[0.653,0.679,-0.024],[0.678,0.626,-0.030],
          [0.697,0.573,-0.034],[0.709,0.525,-0.037],[0.617,0.596,-0.023],
          [0.628,0.516,-0.030],[0.636,0.454,-0.035],[0.642,0.402,-0.039],
          [0.582,0.587,-0.022],[0.583,0.497,-0.029],[0.583,0.429,-0.034],
          [0.584,0.374,-0.038],[0.550,0.599,-0.021],[0.542,0.519,-0.028],
          [0.536,0.460,-0.033],[0.531,0.411,-0.036],[0.520,0.621,-0.019],
          [0.503,0.555,-0.026],[0.492,0.506,-0.030],[0.484,0.466,-0.033]
        ],
        "features": {
          "wrist_position": [0.622,0.724,-0.016],
          "palm_center": [0.578,0.602,-0.021],
          "palm_normal": [-0.074,-0.918,0.390],
          "openness": 0.79,
          "finger_states": [1,1,1,1,1],
          "pinch_distance": 0.181,
          "wrist_velocity": [-0.116,-0.428,0.014],
          "wrist_acceleration": [-0.442,-1.214,0.051],
          "motion_direction": "down"
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
      "sequence": 9632,
      "valid": true,
      "timestamps": {
        "device_timestamp_ms": 192640,
        "pi_receive_timestamp_ns": 153482304800000,
        "pi_mapped_sample_timestamp_ns": 153482298900000,
        "pi_aligned_timestamp_ns": 153482300000000
      },
      "raw_interpolated": {
        "acceleration_mg": [84.0,1164.0,-362.0],
        "pitch_deg": 18.0,
        "roll_deg": -7.0
      },
      "instant_features": {
        "acceleration_g": [0.084,1.164,-0.362],
        "acceleration_magnitude_g": 1.221,
        "gravity_g": [0.021,0.982,-0.138],
        "linear_acceleration_g": [0.063,0.182,-0.224],
        "linear_acceleration_magnitude_g": 0.295,
        "jerk_magnitude_g_s": 4.19,
        "motion_energy": 0.087
      },
      "ble": {
        "rssi_dbm": -58,
        "recent_sample_rate_hz": 24.8,
        "recent_loss_ratio": 0.01,
        "connected": true
      },
      "sync": {
        "clock_ready": true,
        "method": "clock_mapping_and_linear_interpolation",
        "sync_rtt_ms": 11.2,
        "clock_drift_ppm": 8.6,
        "source_sequences": [9631,9632],
        "interpolation_ratio": 0.54,
        "nearest_sample_error_ms": 7.5,
        "bracket_span_ms": 38.4
      }
    },
    {
      "source": "microbit_ble",
      "device_id": "MB_RIGHT",
      "hand": "right",
      "ble_address": "AA:BB:CC:DD:EE:02",
      "sequence": 9514,
      "valid": true,
      "timestamps": {
        "device_timestamp_ms": 190280,
        "pi_receive_timestamp_ns": 153482305300000,
        "pi_mapped_sample_timestamp_ns": 153482299300000,
        "pi_aligned_timestamp_ns": 153482300000000
      },
      "raw_interpolated": {
        "acceleration_mg": [-102.0,1388.0,-418.0],
        "pitch_deg": 21.0,
        "roll_deg": 6.0
      },
      "instant_features": {
        "acceleration_g": [-0.102,1.388,-0.418],
        "acceleration_magnitude_g": 1.453,
        "gravity_g": [-0.027,0.991,-0.151],
        "linear_acceleration_g": [-0.075,0.397,-0.267],
        "linear_acceleration_magnitude_g": 0.484,
        "jerk_magnitude_g_s": 6.01,
        "motion_energy": 0.234
      },
      "ble": {
        "rssi_dbm": -61,
        "recent_sample_rate_hz": 24.6,
        "recent_loss_ratio": 0.02,
        "connected": true
      },
      "sync": {
        "clock_ready": true,
        "method": "clock_mapping_and_linear_interpolation",
        "sync_rtt_ms": 12.1,
        "clock_drift_ppm": -11.4,
        "source_sequences": [9513,9514],
        "interpolation_ratio": 0.49,
        "nearest_sample_error_ms": 8.1,
        "bracket_span_ms": 39.2
      }
    }
  ],

  "fusion": {
    "valid": true,
    "alignment_method": "camera_sensor_timestamp_as_target",
    "camera_valid": true,
    "left_hand_valid": true,
    "right_hand_valid": true,
    "left_microbit_valid": true,
    "right_microbit_valid": true,
    "cross_modal_features": {
      "left_visual_imu_consistency": 0.87,
      "right_visual_imu_consistency": 0.92,
      "left_visual_imu_peak_offset_ms": 10.4,
      "right_visual_imu_peak_offset_ms": 12.1,
      "left_right_motion_correlation": 0.76,
      "beat_candidate": true,
      "beat_hand": "right",
      "beat_strength": 0.83,
      "combined_motion_intensity": 0.78
    },
    "quality": {
      "valid": true,
      "mean_sync_error_ms": 7.8,
      "max_sync_error_ms": 8.1,
      "reason": null
    }
  }
}
```

## 4.4 字段分组说明

### `camera`

只包含摄像头及视觉算法产生的数据。

| 子字段 | 作用 |
|---|---|
| `frame_id` | 摄像头帧编号 |
| `sensor_timestamp_ns` | 摄像头硬件帧时间，也是融合目标 |
| `mediapipe_timestamp_ms` | MediaPipe 使用的毫秒时间 |
| `hands[]` | 当前帧识别到的手 |
| `landmarks_normalized` | 21 个归一化关键点 |
| `features` | 从关键点计算的即时视觉特征 |

### `microbits[]`

数组中固定放左、右两个设备。

| 子字段 | 作用 |
|---|---|
| `device_id` | 逻辑设备 ID |
| `hand` | 左手或右手 |
| `sequence` | BLE 样本序号 |
| `timestamps` | 设备时间、接收时间、映射时间和对齐时间 |
| `raw_interpolated` | 插值到摄像头时间的原始传感器值 |
| `instant_features` | 树莓派计算的 IMU 即时特征 |
| `ble` | BLE 信号、采样率和丢包情况 |
| `sync` | 时钟同步与插值质量 |

### `fusion`

只包含树莓派融合算法产生的数据。

| 子字段 | 作用 |
|---|---|
| `alignment_method` | 说明以摄像头时间为目标 |
| `*_valid` | 各数据源是否有效 |
| `cross_modal_features` | 视觉与 IMU 联合特征 |
| `quality` | 当前融合帧质量 |

---

# 5. `window_features`

## 5.1 作用

`window_features` 表示：

> 对最近一段时间内多个 `fused_frame` 进行统计后得到的动态特征。

推荐：

```text
窗口长度：800 ms
窗口步长：100 ms
```

## 5.2 包含关系

```text
window_features
├── window
├── source_summary
├── camera_features
├── microbit_features
├── cross_modal_features
├── inference
└── quality
```

## 5.3 完整 JSON 示例

```json
{
  "schema_version": "1.1",
  "message_type": "window_features",
  "session_id": "session-20260715-001",
  "packet_sequence": 10249,
  "pi_id": "raspberrypi-01",
  "timestamps": {
    "pi_packet_created_mono_ns": 153482318600000,
    "pi_unix_time_ns": 1783933212348678900
  },
  "window": {
    "window_id": 1254,
    "start_timestamp_ns": 153481500000000,
    "end_timestamp_ns": 153482300000000,
    "center_timestamp_ns": 153481900000000,
    "duration_ms": 800,
    "hop_ms": 100
  },
  "source_summary": {
    "camera_frame_count": 24,
    "camera_expected_count": 24,
    "camera_missing_ratio": 0.0,
    "left_ble_sample_count": 20,
    "left_ble_expected_count": 20,
    "left_ble_missing_ratio": 0.0,
    "right_ble_sample_count": 20,
    "right_ble_expected_count": 20,
    "right_ble_missing_ratio": 0.0,
    "mean_sync_error_ms": 7.9,
    "max_sync_error_ms": 18.2
  },
  "camera_features": {
    "left_hand": {
      "sample_count": 24,
      "trajectory_length": 0.482,
      "displacement": [0.018,0.346,-0.012],
      "mean_wrist_speed": 0.63,
      "max_wrist_speed": 1.48,
      "mean_wrist_acceleration": 1.72,
      "max_wrist_acceleration": 3.24,
      "vertical_range": 0.391,
      "horizontal_range": 0.084,
      "depth_range": 0.026,
      "direction_changes": 1,
      "mean_openness": 0.74,
      "std_openness": 0.08,
      "openness_change": 0.06
    },
    "right_hand": {
      "sample_count": 24,
      "trajectory_length": 0.531,
      "displacement": [-0.021,0.418,-0.008],
      "mean_wrist_speed": 0.72,
      "max_wrist_speed": 1.61,
      "mean_wrist_acceleration": 1.91,
      "max_wrist_acceleration": 3.68,
      "vertical_range": 0.425,
      "horizontal_range": 0.091,
      "depth_range": 0.031,
      "direction_changes": 1,
      "mean_openness": 0.68,
      "std_openness": 0.11,
      "openness_change": -0.04
    }
  },
  "microbit_features": {
    "left_hand": {
      "sample_count": 20,
      "mean_acceleration_axis_g": [0.041,1.021,-0.176],
      "std_acceleration_axis_g": [0.083,0.146,0.092],
      "mean_acceleration_magnitude_g": 1.08,
      "std_acceleration_magnitude_g": 0.16,
      "max_acceleration_magnitude_g": 1.42,
      "mean_linear_magnitude_g": 0.17,
      "max_linear_magnitude_g": 0.46,
      "rms_linear_magnitude_g": 0.21,
      "motion_energy": 0.044,
      "mean_jerk_g_s": 2.74,
      "max_jerk_g_s": 7.32,
      "peak_count": 1,
      "peak_timestamps_ns": [153482281300000],
      "dominant_frequency_hz": 1.92,
      "mean_pitch_deg": 14.2,
      "std_pitch_deg": 3.8,
      "mean_roll_deg": -4.6,
      "std_roll_deg": 2.1
    },
    "right_hand": {
      "sample_count": 20,
      "mean_acceleration_axis_g": [-0.063,1.088,-0.214],
      "std_acceleration_axis_g": [0.114,0.218,0.126],
      "mean_acceleration_magnitude_g": 1.12,
      "std_acceleration_magnitude_g": 0.24,
      "max_acceleration_magnitude_g": 1.92,
      "mean_linear_magnitude_g": 0.24,
      "max_linear_magnitude_g": 0.71,
      "rms_linear_magnitude_g": 0.29,
      "motion_energy": 0.084,
      "mean_jerk_g_s": 3.15,
      "max_jerk_g_s": 9.84,
      "peak_count": 1,
      "peak_timestamps_ns": [153482282500000],
      "dominant_frequency_hz": 1.96,
      "mean_pitch_deg": 18.7,
      "std_pitch_deg": 4.9,
      "mean_roll_deg": 5.1,
      "std_roll_deg": 2.8
    }
  },
  "cross_modal_features": {
    "left_visual_imu_correlation": 0.86,
    "right_visual_imu_correlation": 0.89,
    "left_right_visual_correlation": 0.74,
    "left_right_imu_correlation": 0.77,
    "left_visual_imu_peak_offset_ms": 10.4,
    "right_visual_imu_peak_offset_ms": 12.1,
    "left_right_strongest_peak_offset_ms": -12.0,
    "beat_interval_ms": 508.0,
    "estimated_bpm": 118.1,
    "combined_motion_intensity": 0.81,
    "dominant_hand": "right"
  },
  "inference": {
    "model_name": "gesture_fusion_v1",
    "model_version": "1.0.0",
    "gesture": "downbeat",
    "gesture_confidence": 0.94,
    "class_probabilities": {
      "still": 0.01,
      "left_wrist_strike": 0.02,
      "right_wrist_strike": 0.18,
      "bilateral_strike": 0.09,
      "downbeat": 0.66,
      "upbeat": 0.04
    },
    "continuous_controls": {
      "tempo_delta": 0.12,
      "volume": 0.73,
      "intensity": 0.81,
      "articulation": 0.58,
      "left_weight": 0.32,
      "right_weight": 0.68
    }
  },
  "quality": {
    "valid": true,
    "window_coverage_ratio": 0.97,
    "camera_quality_score": 0.95,
    "left_ble_quality_score": 0.92,
    "right_ble_quality_score": 0.90,
    "fusion_quality_score": 0.91,
    "reason": null
  }
}
```

## 5.4 字段分组说明

| 分组 | 作用 |
|---|---|
| `window` | 定义该窗口的起止时间、长度和步长 |
| `source_summary` | 说明参与计算的原始数据是否完整 |
| `camera_features` | 左右手视觉轨迹与速度统计 |
| `microbit_features` | 左右手 IMU 动态统计 |
| `cross_modal_features` | 视觉、IMU 和左右手之间的联合特征 |
| `inference` | 模型输出 |
| `quality` | 当前窗口是否可信 |

---

# 6. `control_event`

## 6.1 作用

`control_event` 是经过模型、阈值、去重和冷却时间处理后的明确控制事件。

一个动作可能连续出现在多个重叠窗口中，但只应生成一次事件。

## 6.2 完整 JSON 示例

```json
{
  "schema_version": "1.1",
  "message_type": "control_event",
  "session_id": "session-20260715-001",
  "packet_sequence": 10250,
  "pi_id": "raspberrypi-01",
  "timestamps": {
    "event_timestamp_ns": 153482282500000,
    "pi_packet_created_mono_ns": 153482319100000,
    "pi_unix_time_ns": 1783933212353678900
  },
  "event": {
    "event_id": "event-00831",
    "type": "downbeat",
    "hand": "right",
    "confidence": 0.94,
    "strength": 0.83,
    "duration_ms": 120,
    "phase": "triggered"
  },
  "source_window": {
    "window_id": 1254,
    "start_timestamp_ns": 153481500000000,
    "end_timestamp_ns": 153482300000000,
    "model_name": "gesture_fusion_v1",
    "model_version": "1.0.0"
  },
  "music_control": {
    "estimated_bpm": 118.1,
    "target_bpm": 120.0,
    "tempo_delta": 0.12,
    "volume": 0.73,
    "intensity": 0.81,
    "articulation": 0.58,
    "accent_strength": 0.83,
    "left_instrument_weight": 0.32,
    "right_instrument_weight": 0.68
  },
  "led_control": {
    "enabled": true,
    "pattern": "right_pulse",
    "brightness": 0.25,
    "duration_ms": 120,
    "left_panel_weight": 0.20,
    "right_panel_weight": 0.80
  },
  "delivery": {
    "requires_ack": false,
    "deduplication_key": "event-00831",
    "expires_after_ms": 300
  }
}
```

## 6.3 字段分组说明

| 分组 | 作用 |
|---|---|
| `event` | 说明发生了什么动作 |
| `source_window` | 指明事件来源于哪个窗口和模型 |
| `music_control` | PC 应执行的音乐参数 |
| `led_control` | 树莓派 LED 实际行为的同步记录 |
| `delivery` | 去重、过期和确认策略 |

---

# 7. `status`

## 7.1 作用

`status` 不描述手势，而是描述系统是否正常。

## 7.2 完整 JSON 示例

```json
{
  "schema_version": "1.1",
  "message_type": "status",
  "session_id": "session-20260715-001",
  "packet_sequence": 10251,
  "pi_id": "raspberrypi-01",
  "timestamps": {
    "pi_packet_created_mono_ns": 153482320000000,
    "pi_unix_time_ns": 1783933212362678900
  },
  "system": {
    "uptime_s": 1842.6,
    "cpu_usage_percent": 46.2,
    "memory_usage_percent": 38.7,
    "cpu_temperature_c": 58.4,
    "processing_loop_hz": 29.1,
    "healthy": true
  },
  "camera": {
    "connected": true,
    "backend": "picamera2",
    "configured_fps": 30,
    "actual_capture_fps": 29.8,
    "actual_inference_fps": 29.1,
    "width": 640,
    "height": 480,
    "dropped_frames_recent": 1,
    "last_frame_age_ms": 18.2,
    "mean_processing_latency_ms": 12.7,
    "valid_hand_detection_ratio": 0.94,
    "error": null
  },
  "microbits": {
    "left": {
      "device_id": "MB_LEFT",
      "hand": "left",
      "transport": "ble",
      "ble_address": "AA:BB:CC:DD:EE:01",
      "connected": true,
      "rssi_dbm": -58,
      "target_sample_rate_hz": 25,
      "recent_sample_rate_hz": 24.8,
      "recent_received_samples": 124,
      "recent_lost_samples": 1,
      "recent_loss_ratio": 0.008,
      "last_sample_age_ms": 27.4,
      "clock_ready": true,
      "sync_points": 12,
      "sync_rtt_ms": 11.2,
      "clock_drift_ppm": 8.6,
      "reconnect_count": 0,
      "error": null
    },
    "right": {
      "device_id": "MB_RIGHT",
      "hand": "right",
      "transport": "ble",
      "ble_address": "AA:BB:CC:DD:EE:02",
      "connected": true,
      "rssi_dbm": -61,
      "target_sample_rate_hz": 25,
      "recent_sample_rate_hz": 24.6,
      "recent_received_samples": 123,
      "recent_lost_samples": 2,
      "recent_loss_ratio": 0.016,
      "last_sample_age_ms": 30.1,
      "clock_ready": true,
      "sync_points": 12,
      "sync_rtt_ms": 12.1,
      "clock_drift_ppm": -11.4,
      "reconnect_count": 1,
      "error": null
    }
  },
  "fusion": {
    "fused_frame_rate_hz": 29.0,
    "window_feature_rate_hz": 10.0,
    "mean_sync_error_ms": 7.9,
    "max_sync_error_ms": 18.2,
    "valid_fused_frame_ratio": 0.93,
    "valid_window_ratio": 0.96,
    "left_buffer_samples": 247,
    "right_buffer_samples": 244,
    "camera_buffer_frames": 58,
    "error": null
  },
  "network": {
    "protocol": "tcp_jsonl",
    "pc_host": "192.168.1.100",
    "pc_port": 9000,
    "connected": true,
    "queued_messages": 2,
    "sent_messages": 10251,
    "dropped_messages": 0,
    "send_rate_hz": 40.1,
    "reconnect_count": 1,
    "last_send_age_ms": 8.6,
    "error": null
  },
  "led": {
    "enabled": true,
    "backend": "rpi_ws281x",
    "gpio": 18,
    "panel_model": "WS2812B_8x32",
    "panel_count": 2,
    "total_leds": 512,
    "brightness_limit": 0.25,
    "current_brightness": 0.18,
    "refresh_rate_hz": 50,
    "current_pattern": "right_pulse",
    "dropped_render_frames": 0,
    "error": null
  }
}
```

## 7.3 字段分组说明

| 分组 | 作用 |
|---|---|
| `system` | CPU、内存、温度和主循环 |
| `camera` | 摄像头连接、FPS、丢帧和推理延迟 |
| `microbits.left/right` | BLE、采样率、丢包和时钟同步 |
| `fusion` | 融合频率、同步误差和缓存 |
| `network` | 树莓派 → PC 连接和发送队列 |
| `led` | WS2812B 灯板运行状态 |

---

# 8. 树莓派内部如何生成四类数据

## 8.1 总体流程

```text
摄像头采集
    │
    ▼
MediaPipe 关键点和视觉特征
    │
    ├───────────────────────┐
    │                       │
双 micro:bit BLE 接收       │
    │                       │
    ▼                       │
设备时间映射                │
    │                       │
    ▼                       │
左右样本缓冲                │
    │                       │
    └──────────┬────────────┘
               ▼
  以摄像头时间为目标进行插值
               │
               ▼
         fused_frame
               │
               ▼
       滑动窗口统计
               │
               ▼
      window_features
               │
               ▼
      模型 + 事件状态机
               │
               ▼
        control_event

状态统计线程
└── status
```

## 8.2 处理步骤

1. 摄像头生成一帧，并取得 `SensorTimestamp`。
2. MediaPipe 输出左右手关键点。
3. 树莓派计算视觉即时特征。
4. 两块 micro:bit 通过 BLE 发送设备时间和 IMU 数据。
5. 树莓派将每块 micro:bit 的设备时间映射到树莓派时间轴。
6. 左右 micro:bit 样本分别放入环形缓冲。
7. 以摄像头帧时间为目标，在两个缓冲中寻找前后样本。
8. 对 `ax/ay/az/pitch/roll` 进行线性插值。
9. 计算 IMU 即时特征。
10. 按 `left ↔ MB_LEFT`、`right ↔ MB_RIGHT` 进行跨模态匹配。
11. 生成 `fused_frame`。
12. 将 `fused_frame` 加入 800 ms 滑动窗口。
13. 计算视觉、IMU 和跨模态窗口特征。
14. 生成 `window_features`。
15. 将窗口特征输入规则或 AI 模型。
16. 经过阈值、去重和冷却时间后生成 `control_event`。
17. 独立状态线程每秒生成 `status`。

---

# 9. 时间戳同步实现

## 9.1 系统中的时钟

系统中存在：

```text
左 micro:bit 本地时钟
右 micro:bit 本地时钟
摄像头 SensorTimestamp
树莓派 monotonic_ns
PC 本地时钟
```

这些时钟不能直接比较。

## 9.2 树莓派主时间轴

树莓派内部统一使用：

```python
time.monotonic_ns()
```

它单调递增，不受系统日期修改影响，适合计算时间差。

## 9.3 摄像头时间

CSI 摄像头优先使用：

```python
metadata["SensorTimestamp"]
```

该时间作为：

```text
fusion_target_timestamp_ns
```

## 9.4 micro:bit 本地时间

micro:bit 使用：

```typescript
input.runningTime()
```

单位为毫秒。

左右两块 micro:bit 必须分别同步。

## 9.5 BLE 双向同步

树莓派发送：

```text
SYNC,<sync_id>
```

记录发送时间：

\[
t_0
\]

micro:bit 收到后记录：

\[
m_1
\]

并返回：

```text
SYNC_ACK,<sync_id>,<m1>
```

树莓派收到时记录：

\[
t_2
\]

估计 micro:bit 时间 `m1` 对应的树莓派时间：

\[
t_{mid}=\frac{t_0+t_2}{2}
\]

往返时间：

\[
RTT=t_2-t_0
\]

## 9.6 时钟映射

收集多个同步点：

```text
(microbit_time, pi_midpoint_time)
```

拟合：

\[
t_{Pi}=a\cdot t_{microbit}+b
\]

其中：

- `a`：时钟漂移；
- `b`：时钟偏移。

推荐：

```text
启动时同步 10～20 次
选取 RTT 最小的 5～10 个点
运行中每 10～30 秒重新同步
BLE 重连后清空旧映射并重新同步
```

## 9.7 样本时间映射

```python
device_timestamp_ns = (
    device_timestamp_ms * 1_000_000
)

pi_mapped_timestamp_ns = int(
    a * device_timestamp_ns + b
)
```

## 9.8 插值到摄像头时间

目标时间：

```text
target = camera.sensor_timestamp_ns
```

找到：

```text
sample0.time <= target <= sample1.time
```

插值比例：

\[
r=\frac{target-t_0}{t_1-t_0}
\]

插值：

\[
x(t)=x_0+r(x_1-x_0)
\]

对以下字段分别插值：

```text
ax
ay
az
pitch
roll
```

## 9.9 同步质量字段

每次插值都记录：

| 字段 | 含义 |
|---|---|
| `source_sequences` | 插值前后样本序号 |
| `interpolation_ratio` | 目标时间在两个样本之间的位置 |
| `nearest_sample_error_ms` | 目标时间距最近样本的时间差 |
| `bracket_span_ms` | 前后样本时间跨度 |
| `sync_rtt_ms` | 最近同步 RTT |
| `clock_drift_ppm` | 时钟漂移 |

建议判定无效：

```text
clock_ready == false
BLE disconnected
bracket_span_ms > 100
nearest_sample_error_ms > 60
```

## 9.10 树莓派与 PC 时间

树莓派与 PC 的 `monotonic_ns()` 起点不同，不能直接相减。

树莓派发送：

```text
pi_packet_created_mono_ns
pi_unix_time_ns
```

PC 收到时本地记录：

```text
pc_receive_mono_ns
pc_receive_unix_ns
```

跨设备延迟可通过同步后的 Unix 时间粗略估算。

---

# 10. 最终总结

```text
fused_frame
=
一个摄像头时刻的视觉数据
+
左手 micro:bit 插值数据
+
右手 micro:bit 插值数据
+
即时融合特征

window_features
=
最近 800 ms 内多个 fused_frame 的统计结果

control_event
=
模型识别并经状态机确认的高级控制事件

status
=
摄像头、BLE、同步、网络、树莓派和 LED 的健康状态
```

时间同步的核心原则：

```text
树莓派 monotonic_ns 作为统一时间轴
摄像头 SensorTimestamp 作为每帧融合目标
左右 micro:bit 分别建立时钟映射
BLE 数据线性插值到摄像头帧时间
```
