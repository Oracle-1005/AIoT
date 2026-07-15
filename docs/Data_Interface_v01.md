# AIoT 智能指挥系统完整数据接口与通信规范（BLE + 树莓派直控 LED 版）

## 1. 文档范围

本文档重新统一定义以下四条链路：

1. **双 micro:bit → 树莓派**
   - 通信方式改为 Bluetooth Low Energy（BLE）
2. **摄像头 → 树莓派**
   - 使用 CSI 摄像头或 USB 摄像头
3. **树莓派 → PC**
   - 传输融合特征、窗口特征、控制事件和状态数据
4. **树莓派 → WS2812B LED 8×32 灯板**
   - 由于当前没有 Arduino、ESP32 或 RP2040，LED 灯板改由树莓派直接控制

系统职责如下：

- micro:bit：采集左右手腕运动数据
- 摄像头：采集双手位置、姿态和运动轨迹
- 树莓派：负责 BLE 接收、摄像头采集、时间同步、特征提取、数据融合、LED 控制和向 PC 发送数据
- PC：负责 AI 推理、音乐控制、界面显示、模型训练和数据存储
- WS2812B LED 灯板：由树莓派 GPIO 直接驱动

---

# 2. 总体架构

```text
左手 micro:bit ─┐
                 ├─ BLE ──────────────┐
右手 micro:bit ─┘                     │
                                       ▼
摄像头 ─ CSI / USB ──────────────── 树莓派
                                       │
                         ┌─────────────┴─────────────┐
                         │                           │
                         │ TCP / WebSocket / MQTT    │ GPIO + PWM/PCM
                         ▼                           ▼
                        PC                    WS2812B LED 灯板
                  ┌──────┼──────┐                 8×32 × 2
                  ▼      ▼      ▼
               AI推理  音乐控制  数据存储
```

推荐最终技术选型：

| 链路 | 推荐方式 |
|---|---|
| micro:bit → 树莓派 | BLE GATT Notification |
| 摄像头 → 树莓派 | CSI + Picamera2 |
| 树莓派 → PC | TCP + JSON Lines |
| 树莓派 → LED | GPIO + `rpi_ws281x` |
| LED 供电 | 独立 5V 电源 |

---

# 3. micro:bit → 树莓派 BLE 接口

## 3.1 BLE 通信架构

每块 micro:bit 作为 BLE 外设：

```text
micro:bit
├── BLE Peripheral
├── 自定义 UART Service 或 Accelerometer Service
└── 周期性发送传感器数据
```

树莓派作为 BLE Central：

```text
Raspberry Pi
├── BlueZ
├── Python Bleak
├── 同时连接两块 micro:bit
└── 订阅 Notify Characteristic
```

推荐使用：

```text
micro:bit Bluetooth UART Service
```

原因：

- 可以自定义数据包
- 方便携带设备 ID、手侧、序号和时间戳
- 比单独使用 Accelerometer Service 更适合双设备同步

---

## 3.2 BLE 设备标识

左手：

```typescript
const DEVICE_ID = "MB_LEFT"
const HAND = "left"
```

右手：

```typescript
const DEVICE_ID = "MB_RIGHT"
const HAND = "right"
```

树莓派需要按：

```text
BLE MAC 地址
+
DEVICE_ID
+
HAND
```

识别设备。

建议配置文件：

```yaml
microbits:
  left:
    id: MB_LEFT
    address: "AA:BB:CC:DD:EE:01"
  right:
    id: MB_RIGHT
    address: "AA:BB:CC:DD:EE:02"
```

注意：

- 部分系统可能使用随机 BLE 地址
- 实际部署时应优先使用扫描结果中的设备名称和广播信息
- 最终绑定关系应写入配置文件

---

## 3.3 BLE 数据包设计

BLE Notification 单包通常不宜过大。

推荐使用紧凑二进制格式，而不是 JSON。

推荐数据结构：

```text
uint8   version
uint8   hand
uint16  sequence
uint32  device_timestamp_ms
int16   ax_mg
int16   ay_mg
int16   az_mg
int16   pitch_deg
int16   roll_deg
uint8   flags
```

总长度：

```text
20 字节
```

字段定义：

| 字段 | 大小 | 类型 | 含义 |
|---|---:|---|---|
| `version` | 1 B | uint8 | 协议版本 |
| `hand` | 1 B | uint8 | 0=left，1=right |
| `sequence` | 2 B | uint16 | 包序号 |
| `device_timestamp_ms` | 4 B | uint32 | micro:bit 启动时间 |
| `ax_mg` | 2 B | int16 | X 轴加速度 |
| `ay_mg` | 2 B | int16 | Y 轴加速度 |
| `az_mg` | 2 B | int16 | Z 轴加速度 |
| `pitch_deg` | 2 B | int16 | Pitch |
| `roll_deg` | 2 B | int16 | Roll |
| `flags` | 1 B | uint8 | 状态位 |

推荐采样率：

```text
25～50 Hz
```

BLE 比 USB 串口更容易产生延迟抖动，因此建议初始使用：

```text
25 Hz
```

稳定后再尝试：

```text
50 Hz
```

---

## 3.4 BLE 文本调试格式

开发初期也可以使用短文本：

```text
L,152,3240,-24,110,-992,6,-1
```

字段：

```text
hand,sequence,timestamp,ax,ay,az,pitch,roll
```

但最终版本推荐二进制包，因为：

- 数据更短
- 解析更快
- 不容易超过 BLE 单包长度
- 延迟更低

---

## 3.5 BLE 服务和特征值

推荐接口：

```text
UART Service
├── RX Characteristic：树莓派 → micro:bit
└── TX Characteristic：micro:bit → 树莓派 Notify
```

micro:bit 发送：

```text
DATA notification
```

树莓派发送：

```text
IDENTIFY
SYNC
SET_RATE
START
STOP
```

---

## 3.6 树莓派 → micro:bit BLE 命令

### IDENTIFY

```text
IDENTIFY
```

micro:bit 返回：

```text
HELLO,MB_LEFT,left,1.0
```

### SYNC

```text
SYNC,<sync_id>
```

micro:bit 返回：

```text
SYNC_ACK,<sync_id>,<device_timestamp_ms>
```

### SET_RATE

```text
SET_RATE,25
```

表示设置为：

```text
25 Hz
```

### START

```text
START
```

开始发送数据。

### STOP

```text
STOP
```

暂停发送数据。

---

# 4. BLE 时间同步

## 4.1 时间源

micro:bit：

```text
input.runningTime()
```

树莓派：

```python
time.monotonic_ns()
```

两者不能直接比较，需要建立映射。

---

## 4.2 双向同步

树莓派发送 `SYNC` 时记录：

\[
t_0
\]

micro:bit 收到时记录：

\[
m_1
\]

树莓派收到 `SYNC_ACK` 时记录：

\[
t_2
\]

估计 micro:bit 时间对应的树莓派时间：

\[
t_{mid}=\frac{t_0+t_2}{2}
\]

时钟映射：

\[
t_{Pi}=a\cdot t_{microbit}+b
\]

其中：

- \(a\)：时钟漂移
- \(b\)：时钟偏移

---

## 4.3 BLE 同步策略

推荐：

```text
启动阶段：
连续同步 10～20 次
选择 RTT 最小的 5 次

运行阶段：
每 10～30 秒重新同步

BLE 重连后：
清空缓冲
重新同步
```

BLE 延迟波动通常高于 USB 串口，因此必须保存：

```text
pi_receive_timestamp_ns
device_timestamp_ms
sync_rtt_ms
```

---

# 5. 摄像头 → 树莓派接口

## 5.1 物理连接

推荐：

```text
Camera Module
    │
    │ CSI
    ▼
树莓派
```

软件：

```text
Picamera2
MediaPipe Hand Landmarker
OpenCV
```

可选：

```text
USB 摄像头 + OpenCV
```

---

## 5.2 推荐参数

| 参数 | 推荐值 |
|---|---|
| 分辨率 | 640×480 |
| 帧率 | 30 FPS |
| 格式 | RGB888 |
| 最大手数 | 2 |
| 模型 | MediaPipe Hand Landmarker |
| 缓冲 | 3～4 帧 |

---

## 5.3 摄像头原始帧结构

树莓派内部：

```json
{
  "frame_id": 4821,
  "sensor_timestamp_ns": 153482300000000,
  "exposure_time_us": 8200,
  "width": 640,
  "height": 480
}
```

原始图像：

```text
NumPy Array
```

不放入 JSON。

---

## 5.4 MediaPipe 输出

```json
{
  "hand_id": "left-0",
  "handedness": "left",
  "confidence": 0.97,
  "landmarks_normalized": [
    [0.514, 0.742, -0.012]
  ],
  "world_landmarks": [
    [0.021, -0.034, 0.006]
  ]
}
```

每只手实际包含 21 个关键点。

---

## 5.5 摄像头特征

树莓派计算：

| 字段 | 含义 |
|---|---|
| `palm_center` | 手掌中心 |
| `palm_normal` | 手掌方向 |
| `openness` | 手掌张开程度 |
| `finger_states` | 手指开合状态 |
| `joint_angles` | 关节角度 |
| `pinch_distance` | 捏合距离 |
| `wrist_position` | 手腕位置 |
| `wrist_velocity` | 手腕速度 |
| `wrist_acceleration` | 手腕加速度 |
| `motion_direction` | 运动方向 |
| `trajectory_length` | 轨迹长度 |
| `hand_distance` | 双手距离 |

---

# 6. 树莓派内部同步与融合

## 6.1 主时间轴

统一使用：

```python
time.monotonic_ns()
```

---

## 6.2 融合目标

以摄像头帧：

```text
SensorTimestamp
```

作为融合目标。

对左右 micro:bit 分别找到：

```text
t0 <= camera_timestamp <= t1
```

线性插值：

\[
x(t)=x_0+\frac{t-t_0}{t_1-t_0}(x_1-x_0)
\]

插值字段：

- `ax`
- `ay`
- `az`
- `pitch`
- `roll`

---

## 6.3 BLE 插值容差

BLE 延迟抖动较大，推荐：

```text
最大插值跨度：100 ms
最大样本年龄：120 ms
```

若超出：

```json
{
  "valid": false,
  "reason": "ble_sample_too_old"
}
```

---

## 6.4 数据层级

树莓派内部同时维护：

```text
raw_camera_frame
raw_ble_sample
fused_frame
window_features
control_event
status
```

---

# 7. 树莓派 → PC 接口

## 7.1 物理网络

```text
树莓派
  │
  │ Ethernet / Wi-Fi
  ▼
PC
```

---

## 7.2 推荐协议

```text
TCP + JSON Lines
```

推荐端口：

```text
9000
```

PC：

```text
TCP Server
```

树莓派：

```text
TCP Client
```

每条消息：

```text
一个 JSON + \n
```

---

## 7.3 公共字段

```json
{
  "schema_version": "1.1",
  "message_type": "fused_frame",
  "session_id": "session-20260714-001",
  "packet_sequence": 10248,
  "pi_id": "raspberrypi-01",
  "timestamps": {
    "pi_packet_created_mono_ns": 153482315600000,
    "pi_unix_time_ns": 1783933212345678900
  }
}
```

---

# 8. `fused_frame` 格式

推荐频率：

```text
20～30 Hz
```

```json
{
  "schema_version": "1.1",
  "message_type": "fused_frame",
  "session_id": "session-20260714-001",
  "packet_sequence": 10248,

  "timestamps": {
    "fusion_target_timestamp_ns": 153482300000000,
    "pi_packet_created_mono_ns": 153482315600000,
    "pi_unix_time_ns": 1783933212345678900
  },

  "camera": {
    "source": "camera",
    "frame_id": 4821,
    "sensor_timestamp_ns": 153482300000000,
    "width": 640,
    "height": 480,
    "fps": 30,

    "hands": [
      {
        "hand_id": "left-0",
        "handedness": "left",
        "confidence": 0.97,
        "valid": true,
        "landmarks_normalized": [
          [0.514, 0.742, -0.012]
        ],
        "features": {
          "palm_center": [0.507, 0.613, -0.019],
          "openness": 0.78,
          "wrist_velocity": [0.18, -0.43, 0.02]
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
        "jerk_magnitude_g_s": 4.82
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
        "bracket_span_ms": 38.4
      }
    }
  ],

  "fusion": {
    "valid": true,
    "alignment_method": "camera_timestamp_target",
    "cross_modal_features": {
      "beat_candidate": true,
      "beat_strength": 0.83,
      "vision_imu_consistency": 0.91,
      "combined_motion_intensity": 0.76
    }
  }
}
```

---

# 9. `window_features` 格式

推荐：

```text
窗口长度：800 ms
步长：100 ms
输出频率：10 Hz
```

```json
{
  "schema_version": "1.1",
  "message_type": "window_features",

  "window": {
    "window_id": 1254,
    "start_timestamp_ns": 153481500000000,
    "end_timestamp_ns": 153482300000000,
    "duration_ms": 800,
    "hop_ms": 100
  },

  "source_summary": {
    "camera_frame_count": 24,
    "left_ble_sample_count": 20,
    "right_ble_sample_count": 20,
    "mean_sync_error_ms": 8.1,
    "max_sync_error_ms": 18.7
  },

  "camera_features": {
    "left_hand": {
      "trajectory_length": 0.482,
      "mean_wrist_speed": 0.63,
      "max_wrist_speed": 1.48
    },
    "right_hand": {
      "trajectory_length": 0.531,
      "mean_wrist_speed": 0.72,
      "max_wrist_speed": 1.61
    }
  },

  "microbit_features": {
    "left_hand": {
      "max_acceleration_magnitude_g": 1.42,
      "max_jerk_g_s": 7.32,
      "motion_energy": 0.18,
      "peak_count": 1
    },
    "right_hand": {
      "max_acceleration_magnitude_g": 1.92,
      "max_jerk_g_s": 9.84,
      "motion_energy": 0.27,
      "peak_count": 1
    }
  },

  "cross_modal_features": {
    "left_visual_imu_correlation": 0.86,
    "right_visual_imu_correlation": 0.89,
    "estimated_bpm": 118.1,
    "combined_motion_intensity": 0.81
  },

  "quality": {
    "valid": true,
    "window_coverage_ratio": 0.97
  }
}
```

---

# 10. `control_event` 格式

```json
{
  "schema_version": "1.1",
  "message_type": "control_event",
  "event_id": "event-00831",

  "event": {
    "type": "downbeat",
    "hand": "right",
    "confidence": 0.94,
    "strength": 0.83
  },

  "music_control": {
    "estimated_bpm": 118.1,
    "volume": 0.73,
    "intensity": 0.81
  },

  "led_control": {
    "pattern": "right_pulse",
    "brightness": 0.55,
    "duration_ms": 120
  }
}
```

该字段既发送给 PC，也供树莓派本地 LED 控制模块使用。

---

# 11. `status` 格式

```json
{
  "message_type": "status",

  "camera": {
    "connected": true,
    "fps": 29.4
  },

  "microbits": {
    "left": {
      "device_id": "MB_LEFT",
      "transport": "ble",
      "connected": true,
      "rssi_dbm": -58,
      "sample_rate_hz": 24.8,
      "recent_loss_ratio": 0.01,
      "clock_ready": true
    },

    "right": {
      "device_id": "MB_RIGHT",
      "transport": "ble",
      "connected": true,
      "rssi_dbm": -61,
      "sample_rate_hz": 24.6,
      "recent_loss_ratio": 0.02,
      "clock_ready": true
    }
  },

  "network": {
    "pc_connected": true,
    "dropped_messages": 0
  },

  "led": {
    "connected": true,
    "backend": "rpi_ws281x",
    "brightness_limit": 0.25,
    "fps": 50
  }
}
```

---

# 12. 树莓派 → WS2812B LED 8×32

## 12.1 是否可以直接由树莓派控制

可以。

当前没有 Arduino、ESP32 或 RP2040 时，可以使用：

```text
树莓派 GPIO
+
rpi_ws281x
+
独立 5V 电源
```

控制 WS2812B。

---

## 12.2 灯板数量

项目中有两块：

```text
WS2812B LED 8×32
```

每块：

```text
256 颗 LED
```

总计：

```text
512 颗 LED
```

---

## 12.3 推荐连接

```text
树莓派 GPIO18
      │
      │ 3.3V 数据
      ▼
74AHCT125 / 74HCT245 电平转换
      │
      │ 5V 数据
      ▼
第一块 LED DIN
      │
      └── DOUT → 第二块 LED DIN
```

供电：

```text
独立 5V 电源
├── LED 板 5V
├── LED 板 GND
└── 与树莓派 GND 共地
```

---

## 12.4 是否必须使用电平转换

强烈建议使用：

```text
74AHCT125
74HCT245
```

原因：

- 树莓派 GPIO 是 3.3V
- WS2812B 通常按 5V 逻辑工作
- 某些短线场景下 3.3V 可能勉强工作
- 但不稳定，容易闪烁或数据错误

如果暂时没有电平转换模块，可以短距离测试：

```text
GPIO18 → 330 Ω 电阻 → LED DIN
```

但不建议作为最终演示方案。

---

## 12.5 GPIO 选择

推荐：

```text
GPIO18
```

物理引脚：

```text
Pin 12
```

常用于 PWM 驱动 `rpi_ws281x`。

接地：

```text
树莓派 GND
LED 电源 GND
LED 板 GND
必须共地
```

---

## 12.6 电源要求

理论最大电流：

\[
512\times60mA=30.72A
\]

这是全白全亮的理论值。

项目中建议：

```text
亮度限制：20%～30%
禁止全白全亮
```

推荐电源：

```text
5V 10A～20A
```

实际取决于：

- 最大亮度
- 同时点亮比例
- 动画颜色
- 是否两块板同时高亮

最低要求：

- 独立 5V 电源
- 不能从树莓派 5V 引脚给两块板供电
- 不能从 PC USB 给灯板供电

---

## 12.7 供电布线

建议：

```text
每块灯板至少单独接入 5V 和 GND
```

不要只依靠：

```text
第一块板 → 第二块板
```

传递全部电流。

推荐：

```text
5V PSU
├── 第一块板 5V/GND
└── 第二块板 5V/GND
```

同时：

```text
第一块 DOUT → 第二块 DIN
```

---

## 12.8 保护元件

建议：

| 元件 | 作用 |
|---|---|
| 330～470 Ω 电阻 | 串联在数据线上 |
| 1000 µF 电容 | 接在 LED 电源入口 |
| 保险丝 | 防止短路 |
| 粗电源线 | 减少压降 |
| 多点供电 | 减少尾端颜色异常 |

---

# 13. 树莓派 LED 软件接口

## 13.1 推荐库

```text
rpi_ws281x
```

Python：

```bash
sudo apt install python3-pip
pip install rpi-ws281x
```

部分系统需要：

```bash
sudo python led_controller.py
```

原因是底层 DMA/PWM 访问可能需要较高权限。

---

## 13.2 LED 逻辑布局

两块 8×32 可以按以下方式组织：

### 方式一：左右手独立

```text
左灯板：左手
右灯板：右手
```

推荐用于当前项目。

### 方式二：拼接成 16×32

```text
左板 + 右板
→ 逻辑 16×32
```

适合整体波纹和节拍动画。

---

## 13.3 LED 控制对象

树莓派内部不需要 JSON 串口协议，可直接调用 Python 函数：

```python
led_controller.show_beat(
    hand="right",
    strength=0.83,
)

led_controller.set_state(
    bpm=118.1,
    intensity=0.81,
    left_weight=0.32,
    right_weight=0.68,
)
```

推荐内部接口：

```python
class LedController:
    def show_beat(
        self,
        hand: str,
        strength: float,
        duration_ms: int,
    ) -> None:
        ...

    def set_state(
        self,
        bpm: float,
        intensity: float,
        left_weight: float,
        right_weight: float,
    ) -> None:
        ...

    def clear(self) -> None:
        ...

    def set_brightness(
        self,
        value: float,
    ) -> None:
        ...
```

---

## 13.4 LED 控制消息来源

树莓派本地根据：

```text
control_event
window_features
```

生成 LED 动画。

示例映射：

| 事件 | LED 行为 |
|---|---|
| `right_wrist_strike` | 右灯板脉冲 |
| `left_wrist_strike` | 左灯板脉冲 |
| `bilateral_strike` | 两块灯板同步闪烁 |
| `downbeat` | 中央高亮 |
| BPM 增加 | 动画速度加快 |
| 强度增加 | 亮度和扩散范围增加 |
| 静止 | 低亮度呼吸 |
| 系统断线 | 红色慢闪 |

---

# 14. 树莓派—PC 与 LED 的职责关系

推荐：

```text
树莓派：
负责实时 LED 反馈

PC：
负责 AI、音乐和界面
```

这样做的优点：

- LED 不受网络延迟影响
- PC 断线时 LED 仍可工作
- 控制链路更短
- 不需要额外控制器
- 树莓派可以直接使用融合结果

PC 仍可通过树莓派发送配置命令：

```json
{
  "message_type": "led_config",
  "brightness_limit": 0.25,
  "pattern": "wave"
}
```

树莓派接收后更新 LED 模式。

---

# 15. 推荐发送频率

| 链路 | 数据 | 推荐频率 |
|---|---|---:|
| micro:bit → 树莓派 | BLE Notification | 25～50 Hz |
| 树莓派 → micro:bit | SYNC | 10～30 秒一次 |
| 摄像头 → 树莓派 | 图像帧 | 30 FPS |
| 树莓派内部融合 | `fused_frame` | 20～30 Hz |
| 树莓派 → PC | `fused_frame` | 20～25 Hz |
| 树莓派 → PC | `window_features` | 10 Hz |
| 树莓派 → PC | `control_event` | 事件触发 |
| 树莓派 → PC | `status` | 1 Hz |
| 树莓派 → LED | 状态刷新 | 30～60 FPS |
| 树莓派 → LED | 节拍事件 | 事件触发 |

---

# 16. 断线处理

## 16.1 BLE 断线

树莓派应：

1. 标记对应 micro:bit 无效
2. 停止使用旧数据
3. 保留另一只手和摄像头模式
4. 重新扫描设备
5. 自动重连
6. 重连后重新同步时钟
7. 清空旧样本缓冲

---

## 16.2 摄像头断线

树莓派应：

1. 标记摄像头无效
2. 保留 micro:bit 模式
3. 尝试重新初始化
4. 恢复后清空视觉轨迹

---

## 16.3 PC 断线

树莓派应：

1. 本地继续融合
2. LED 继续运行
3. 保存 JSONL
4. 自动重连 PC
5. 丢弃过期 `fused_frame`
6. 优先保存 `control_event`

---

## 16.4 LED 异常

树莓派应：

1. 捕获驱动异常
2. 标记 LED 不可用
3. 不影响 BLE、摄像头和 PC 通信
4. 降低亮度或清屏
5. 在 `status` 中报告异常

---

# 17. 推荐最终配置

```yaml
microbit:
  transport: ble_uart
  target_sample_rate_hz: 25
  packet_format: binary_20_bytes
  devices:
    - id: MB_LEFT
      hand: left
      address: LEFT_BLE_ADDRESS
    - id: MB_RIGHT
      hand: right
      address: RIGHT_BLE_ADDRESS

camera:
  transport: csi
  backend: picamera2
  width: 640
  height: 480
  fps: 30
  max_hands: 2

fusion:
  master_clock: raspberry_pi_monotonic_ns
  target: camera_sensor_timestamp
  interpolation: linear
  max_ble_sample_age_ms: 120
  max_interpolation_span_ms: 100
  window_ms: 800
  hop_ms: 100

pi_to_pc:
  protocol: tcp_jsonl
  host: PC_IP
  port: 9000
  fused_frame_hz: 25
  window_features_hz: 10
  status_hz: 1

led:
  model: WS2812B_8x32
  panel_count: 2
  total_leds: 512
  controller: raspberry_pi
  library: rpi_ws281x
  gpio: 18
  level_shifter: 74AHCT125
  external_power: true
  brightness_limit: 0.25
  refresh_hz: 50
```

---

# 18. 最终数据流

```text
左手 micro:bit ─┐
                 ├─ BLE Notification
右手 micro:bit ─┘
                         │
                         ▼
                    BLE 接收与重连
                         │
                         ▼
                    时钟映射与缓存
                         │
                         ├─────────────────────┐
                         │                     │
                    摄像头帧              micro:bit 样本
                         │                     │
                         ▼                     ▼
                  MediaPipe 关键点          线性插值
                         │                     │
                         └──────────┬──────────┘
                                    ▼
                               fused_frame
                                    │
                         ┌──────────┴──────────┐
                         ▼                     ▼
                  window_features         control_event
                         │                     │
                         ▼                     ▼
                   TCP JSON Lines        本地 LED 控制
                         │                     │
                         ▼                     ▼
                        PC              WS2812B 8×32 × 2
```

---

# 19. 最终接口结论

## micro:bit → 树莓派

```text
Bluetooth Low Energy
UART Service
Notification
25～50 Hz
二进制 20 字节数据包
双向时间同步
```

## 摄像头 → 树莓派

```text
CSI + Picamera2
640×480 @ 30 FPS
MediaPipe Hand Landmarker
SensorTimestamp 作为主帧时间
```

## 树莓派 → PC

```text
TCP + JSON Lines
fused_frame
window_features
control_event
status
```

## 树莓派 → LED

```text
GPIO18
rpi_ws281x
74AHCT125 电平转换
两块 WS2812B 8×32
独立 5V 电源
最大建议亮度 20%～30%
```

该版本不再依赖 Arduino、ESP32 或 RP2040。树莓派同时承担感知融合、网络通信和 LED 实时反馈，PC 专注于 AI、音乐和可视化。
