# 树莓派 → PC 数据接口字段说明与多源同步融合处理规范

## 1. 文档目的

本文档详细说明 AIoT 智能指挥系统中：

1. 树莓派向 PC 发送的四类数据：
   - `fused_frame`
   - `window_features`
   - `control_event`
   - `status`
2. 每类数据的用途；
3. 每个字段的含义；
4. 各字段的数据来源；
5. 树莓派内部如何将摄像头数据和双 micro:bit BLE 数据同步、融合并转换为最终发送给 PC 的 JSON 数据。

本文默认系统架构为：

```text
双 micro:bit
    │
    │ BLE
    ▼
树莓派
    ▲
    │ CSI
摄像头
    │
    ▼
树莓派内部同步、特征提取和融合
    │
    │ TCP + JSON Lines
    ▼
PC
```

---

# 2. 树莓派 → PC 接口总体设计

## 2.1 传输方式

推荐使用：

```text
TCP + JSON Lines
```

其中：

- 树莓派作为 TCP Client；
- PC 作为 TCP Server；
- 每条消息是一个完整 JSON；
- 每条 JSON 以换行符 `\n` 结束。

示例：

```text
{"message_type":"fused_frame", ...}\n
{"message_type":"window_features", ...}\n
{"message_type":"control_event", ...}\n
{"message_type":"status", ...}\n
```

推荐端口：

```text
9000
```

## 2.2 为什么使用 JSON Lines

JSON Lines 适合当前项目，原因包括：

- 每条消息边界明确；
- 可以按行读取；
- 可以直接保存为 `.jsonl` 文件；
- Python、JavaScript、Java、C# 都容易解析；
- 便于调试；
- 便于按 `message_type` 分发；
- 一条消息损坏不会影响整个文件。

## 2.3 四类消息的关系

```text
fused_frame
    │
    │ 连续单帧同步数据
    ▼
window_features
    │
    │ 多帧滑动窗口统计
    ▼
control_event
    │
    │ 动作识别或控制结果
    ▼
PC 音乐、AI、界面

status
    │
    └── 独立监控整条链路运行状态
```

| 消息类型 | 表示内容 | 典型频率 | 主要用途 |
|---|---|---:|---|
| `fused_frame` | 某一时刻的同步融合状态 | 20～30 Hz | 实时显示、原始训练数据、调试 |
| `window_features` | 最近一段时间的动态特征 | 5～10 Hz | 动态手势、节拍、AI 模型 |
| `control_event` | 已识别的动作或控制结果 | 事件触发 | 音乐和 LED 控制 |
| `status` | 设备、网络、同步和性能状态 | 1 Hz | 监控、故障诊断 |

---

# 3. 公共顶层字段

四类消息建议包含统一公共字段：

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

## 3.1 `schema_version`

示例：

```json
"schema_version": "1.1"
```

作用：

- 表示当前 JSON 数据结构版本；
- 防止 PC 按旧字段解析新消息；
- 后续增加字段时保持兼容；
- PC 可根据版本选择解析逻辑。

推荐：

```text
1.0：初始版本
1.1：增加 BLE、同步质量或字段
2.0：发生不兼容结构变化
```

## 3.2 `message_type`

示例：

```json
"message_type": "fused_frame"
```

作用：

- 告诉 PC 当前消息属于哪一类；
- PC 根据此字段分发到不同处理模块。

允许值：

```text
fused_frame
window_features
control_event
status
```

## 3.3 `session_id`

示例：

```json
"session_id": "session-20260715-001"
```

作用：

- 标识一次完整运行；
- 区分不同实验；
- 防止不同启动阶段数据混合；
- 用于训练数据分组；
- 用于日志文件命名。

## 3.4 `packet_sequence`

示例：

```json
"packet_sequence": 10248
```

作用：

- 树莓派发送消息的全局序号；
- PC 用于检测网络丢包；
- 检测消息乱序；
- 关联日志；
- 统计实际发送频率。

它不同于：

```text
camera.frame_id
microbit.sequence
window.window_id
event_id
```

## 3.5 `pi_id`

示例：

```json
"pi_id": "raspberrypi-01"
```

作用：

- 标识发送消息的树莓派；
- 后续多树莓派部署时区分来源。

## 3.6 `timestamps.pi_packet_created_mono_ns`

示例：

```json
"pi_packet_created_mono_ns": 153482315600000
```

作用：

- 表示树莓派创建该 JSON 的单调时钟时间；
- 用于树莓派内部处理延迟统计；
- 可计算采集到发送前耗时、特征处理耗时和队列等待时间。

注意：

- 单位为纳秒；
- 起点是树莓派系统启动；
- 不能与 PC 的 `monotonic_ns()` 直接相减。

## 3.7 `timestamps.pi_unix_time_ns`

示例：

```json
"pi_unix_time_ns": 1783933212345678900
```

作用：

- 表示真实日期时间；
- 可与 PC 的 Unix 时间比较；
- 用于日志、文件命名和跨设备粗略延迟估计；
- 前提是树莓派和 PC 都启用 NTP 或 chrony。

---

# 4. `fused_frame` 的作用

## 4.1 定义

`fused_frame` 表示：

> 以某个摄像头帧时间为基准，将该时刻的视觉数据和左右 micro:bit 数据同步到同一时间点后生成的一条融合数据。

它是整个系统中最接近原始数据的一层。

## 4.2 主要用途

- PC 实时绘制手部关键点；
- 显示左右手即时加速度；
- 显示手腕速度和手掌开合；
- 检查同步误差；
- 保存训练原始数据；
- 调试摄像头和 micro:bit 是否一致；
- 为 PC 端时序模型提供输入；
- 连续控制音乐参数。

## 4.3 典型频率

```text
20～30 Hz
```

## 4.4 顶层结构

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
  "camera": {},
  "microbits": [],
  "fusion": {}
}
```

---

# 5. `fused_frame.timestamps`

## 5.1 `fusion_target_timestamp_ns`

作用：

- 当前融合帧的统一目标时间；
- 一般等于摄像头 `SensorTimestamp`；
- 左右 micro:bit 数据都插值到这个时间；
- 是当前融合帧最重要的时间基准。

---

# 6. `fused_frame.camera`

示例：

```json
{
  "camera": {
    "source": "camera",
    "frame_id": 4821,
    "sensor_timestamp_ns": 153482300000000,
    "mediapipe_timestamp_ms": 153482300,
    "width": 640,
    "height": 480,
    "configured_fps": 30,
    "processing_latency_ms": 12.4,
    "hands": []
  }
}
```

## 6.1 `source`

```json
"source": "camera"
```

明确该数据来自摄像头和视觉模块。

## 6.2 `frame_id`

作用：

- 摄像头帧序号；
- 检测丢帧；
- 关联原始视频；
- 将 MediaPipe 异步输出映射回原始帧。

## 6.3 `sensor_timestamp_ns`

作用：

- 摄像头传感器产生该帧的时间；
- 通常来自 Picamera2 `SensorTimestamp`；
- 作为 micro:bit 数据插值的目标时间；
- 比 Python 获取图像后的时间更准确。

## 6.4 `mediapipe_timestamp_ms`

作用：

- MediaPipe 异步接口要求毫秒时间戳；
- 通常由以下方式得到：

```python
sensor_timestamp_ns // 1_000_000
```

## 6.5 `width`、`height`

作用：

- 表示图像分辨率；
- PC 可将归一化关键点换算为像素坐标：

```text
x_pixel = x_normalized × width
y_pixel = y_normalized × height
```

## 6.6 `configured_fps`

作用：

- 表示配置帧率；
- 与 `status.camera.actual_fps` 区分；
- 用于计算理论帧数和缺失比例。

## 6.7 `processing_latency_ms`

作用：

- 表示从摄像头帧可用到完成关键点处理的耗时；
- 用于评估树莓派视觉推理性能。

---

# 7. `camera.hands[]`

每只识别到的手对应一个对象：

```json
{
  "hand_id": "left-0",
  "handedness": "left",
  "confidence": 0.97,
  "valid": true,
  "landmarks_normalized": [],
  "world_landmarks": [],
  "features": {}
}
```

## 7.1 `hand_id`

作用：

- 当前跟踪手的内部 ID；
- 区分多只手；
- 在连续帧中尽量保持稳定；
- 不等于 micro:bit 的设备 ID。

## 7.2 `handedness`

可能值：

```text
left
right
unknown
```

作用：

- MediaPipe 对左右手的判断；
- 与 micro:bit `hand` 字段匹配；
- 进行跨模态关联。

## 7.3 `confidence`

作用：

- 手部检测置信度；
- 低于阈值时不应参与正式融合；
- 可作为模型质量权重。

推荐：

```text
< 0.5：丢弃
0.5～0.7：低可信
> 0.7：正常
```

## 7.4 `valid`

作用：

- 表示当前手数据是否可用；
- 无效原因可能包括置信度低、关键点不完整、遮挡或轨迹跳变。

## 7.5 `landmarks_normalized`

示例：

```json
"landmarks_normalized": [
  [0.514, 0.742, -0.012],
  [0.472, 0.691, -0.018]
]
```

作用：

- MediaPipe 输出的 21 个手部关键点；
- 每个关键点是 `[x,y,z]`；
- 用于手势、手腕位置、手指弯曲和轨迹计算。

## 7.6 `world_landmarks`

作用：

- MediaPipe 估计的三维世界坐标；
- 适合计算相对三维距离；
- 可选字段；
- 数据量较大，最终演示阶段可关闭。

---

# 8. `camera.hands[].features`

## 8.1 `palm_center`

作用：

- 表示手掌中心位置；
- 通常由多个掌部关键点平均计算；
- 用于双手距离和整体轨迹。

## 8.2 `palm_normal`

作用：

- 表示手掌朝向；
- 可判断掌心朝上、朝下或朝前；
- 可映射为渐强、渐弱或模式切换。

## 8.3 `openness`

作用：

- 表示手掌张开程度；
- 一般归一化到 `[0,1]`；
- `0` 接近握拳；
- `1` 接近完全张开。

## 8.4 `finger_states`

```json
"finger_states": [1,1,1,1,1]
```

作用：

- 表示五根手指是否伸展；
- 顺序通常为拇指、食指、中指、无名指、小指。

## 8.5 `joint_angles`

作用：

- 表示手指关节夹角；
- 用于识别握拳、张开、指向和捏合。

## 8.6 `pinch_distance`

作用：

- 拇指尖与食指尖距离；
- 用于检测捏合和连续参数控制。

## 8.7 `wrist_position`

作用：

- 当前手腕位置；
- 一般来自 MediaPipe 第 0 号关键点。

## 8.8 `wrist_velocity`

作用：

- 表示手腕单位时间位移；
- 用于判断挥动方向和速度。

计算：

```text
v(t) = [p(t)-p(t-1)] / Δt
```

## 8.9 `wrist_acceleration`

作用：

- 表示视觉轨迹的二阶变化；
- 用于检测突然加速和停止；
- 可与 micro:bit 加速度比较一致性。

## 8.10 `motion_direction`

可能值：

```text
up
down
left
right
forward
backward
still
```

作用：

- 将速度向量转换为直观方向；
- 适合规则识别和界面显示。

---

# 9. `fused_frame.microbits[]`

每块 micro:bit 对应一个对象：

```json
{
  "source": "microbit_ble",
  "device_id": "MB_LEFT",
  "hand": "left",
  "ble_address": "AA:BB:CC:DD:EE:01",
  "valid": true,
  "timestamps": {},
  "raw_interpolated": {},
  "instant_features": {},
  "ble": {},
  "sync": {}
}
```

## 9.1 `source`

```json
"source": "microbit_ble"
```

明确数据来源于 BLE micro:bit。

## 9.2 `device_id`

作用：

- micro:bit 逻辑 ID；
- 与 BLE 地址分离；
- 即使地址变化，逻辑身份仍可保持。

## 9.3 `hand`

作用：

- 表示该设备佩戴在左手还是右手；
- 与视觉 `handedness` 匹配。

## 9.4 `ble_address`

作用：

- BLE 扫描和连接地址；
- 用于自动重连；
- 某些系统使用随机地址，所以不能单独作为逻辑身份。

## 9.5 `valid`

作用：

- 表示该 micro:bit 在当前融合时刻是否有效；
- 可能无效的原因包括 BLE 断开、样本过旧、时钟未同步或插值失败。

---

# 10. `microbits[].timestamps`

```json
{
  "device_timestamp_ms": 192640,
  "pi_receive_timestamp_ns": 153482304800000,
  "pi_aligned_timestamp_ns": 153482300000000
}
```

## 10.1 `device_timestamp_ms`

作用：

- micro:bit 本地采样时间；
- 来自 `input.runningTime()`；
- 不是树莓派时间；
- 必须经过时钟映射。

## 10.2 `pi_receive_timestamp_ns`

作用：

- 树莓派收到 BLE Notification 的时间；
- 包含 BLE 传输、排队和调度延迟；
- 不能直接视为真实采样时间。

## 10.3 `pi_aligned_timestamp_ns`

作用：

- 将 micro:bit 时间映射到树莓派时间轴后的时间；
- 用于与摄像头时间比较；
- 当前融合值最终会对齐到 `fusion_target_timestamp_ns`。

---

# 11. `microbits[].raw_interpolated`

```json
{
  "acceleration_mg": [84,1164,-362],
  "pitch_deg": 18,
  "roll_deg": -7
}
```

## 11.1 `acceleration_mg`

作用：

- 三轴加速度原始值；
- 单位为 milli-g；
- 已插值到摄像头目标时间；
- 顺序为 `[ax,ay,az]`。

转换：

```text
a_g = a_mg / 1000
```

## 11.2 `pitch_deg`

作用：

- 手腕俯仰角；
- 由 micro:bit 根据加速度估算；
- 快速运动时可能受线性加速度影响。

## 11.3 `roll_deg`

作用：

- 手腕横滚角；
- 用于判断手腕横向倾斜。

---

# 12. `microbits[].instant_features`

## 12.1 `acceleration_g`

作用：

- 将 milli-g 转换为 g；
- 便于统一计算。

## 12.2 `acceleration_magnitude_g`

计算：

```text
|a| = sqrt(ax²+ay²+az²)
```

作用：

- 表示整体加速度强度；
- 不依赖某个单轴方向；
- 适合检测冲击。

## 12.3 `linear_acceleration_g`

作用：

- 从原始加速度中去除重力估计；
- 更接近真实手腕运动加速度；
- 用于动作能量和击拍检测。

## 12.4 `linear_acceleration_magnitude_g`

作用：

- 线性运动加速度模长；
- 比原始合加速度更适合动作识别。

## 12.5 `jerk_g_s`

计算：

```text
j(t) = [a(t)-a(t-1)] / Δt
```

作用：

- 检测加速度变化速度；
- 突然挥动和停止时数值较大。

## 12.6 `jerk_magnitude_g_s`

作用：

- Jerk 三轴模长；
- 适合检测击拍和突发动作。

## 12.7 `motion_energy`

作用：

- 表示当前或短时动作能量；
- 可由线性加速度平方计算；
- 用于音乐强度和 LED 亮度映射。

---

# 13. `microbits[].ble`

```json
{
  "rssi_dbm": -58,
  "notification_sequence": 9632,
  "recent_loss_ratio": 0.01,
  "connection_interval_ms": 30
}
```

## 13.1 `rssi_dbm`

作用：

- BLE 信号强度；
- 数值越接近 0，信号通常越强。

典型判断：

```text
-40 dBm：很强
-60 dBm：正常
-80 dBm：较弱
```

## 13.2 `notification_sequence`

作用：

- micro:bit 数据包序号；
- 检测 BLE 丢包和乱序；
- 不等于树莓派网络消息序号。

## 13.3 `recent_loss_ratio`

作用：

- 最近一段时间内 BLE 数据丢失比例；
- 应采用滑动统计；
- 不建议使用从程序启动开始的永久累计值。

## 13.4 `connection_interval_ms`

作用：

- BLE 连接间隔；
- 影响通知频率和延迟；
- 过大会限制采样率。

---

# 14. `microbits[].sync`

```json
{
  "method": "ble_clock_mapping_and_interpolation",
  "nearest_sample_error_ms": 7.5,
  "bracket_span_ms": 38.4,
  "sync_rtt_ms": 11.2,
  "clock_ready": true
}
```

## 14.1 `method`

说明采用的同步方式。当前推荐：

```text
ble_clock_mapping_and_interpolation
```

## 14.2 `nearest_sample_error_ms`

作用：

- 融合目标时间与最近 micro:bit 样本的时间差；
- 越小越好；
- 用于评估融合可信度。

## 14.3 `bracket_span_ms`

作用：

- 插值前后两个样本之间的时间跨度；
- 太大说明数据稀疏或丢包；
- 超过阈值时应判定无效。

## 14.4 `sync_rtt_ms`

作用：

- 最近一次同步命令往返时间；
- 用于评估 BLE 同步质量；
- RTT 越小，偏移估计通常越可靠。

## 14.5 `clock_ready`

作用：

- 是否已经收集足够同步点；
- `false` 时不应进行正式融合。

---

# 15. `fused_frame.fusion`

```json
{
  "valid": true,
  "alignment_method": "camera_timestamp_target",
  "camera_valid": true,
  "left_microbit_valid": true,
  "right_microbit_valid": true,
  "cross_modal_features": {}
}
```

## 15.1 `valid`

作用：

- 表示整个融合帧是否有效；
- 一般要求摄像头有效、至少一只手有效、对应 micro:bit 有效且同步误差未超阈值。

## 15.2 `alignment_method`

```json
"alignment_method": "camera_timestamp_target"
```

作用：

- 表示以摄像头帧时间为主；
- micro:bit 数据向摄像头时间插值。

## 15.3 `camera_valid`

表示当前摄像头帧是否有效。

## 15.4 `left_microbit_valid`

表示左手 micro:bit 当前融合值是否有效。

## 15.5 `right_microbit_valid`

表示右手 micro:bit 当前融合值是否有效。

---

# 16. `cross_modal_features`

跨模态特征表示摄像头与 micro:bit 的联合结果。

## 16.1 `beat_candidate`

作用：

- 当前时刻是否可能是一次节拍或击拍；
- 通常由视觉手腕速度转折和 micro:bit 加速度峰值联合判断。

## 16.2 `beat_strength`

作用：

- 击拍强度；
- 一般归一化到 `[0,1]`；
- 可映射到音乐重音和 LED 亮度。

## 16.3 `vision_imu_consistency`

作用：

- 摄像头运动与 micro:bit 运动的一致程度；
- 低值可能表示识别错误、佩戴松动、同步误差或左右手匹配错误。

## 16.4 `combined_motion_intensity`

作用：

- 综合视觉速度、IMU 加速度和动作能量；
- 用于连续音乐控制。

---

# 17. `window_features` 的作用

## 17.1 定义

`window_features` 表示：

> 将最近一段时间内的多个 `fused_frame` 汇总后得到的动态统计特征。

默认：

```text
窗口长度：800 ms
窗口步长：100 ms
```

## 17.2 为什么需要滑动窗口

单帧只能描述当前姿态，无法稳定描述：

```text
挥动
画圆
击拍
周期
速度变化
动作能量
BPM
```

动态动作必须观察连续时间。

## 17.3 主要用途

- 动态手势分类；
- 节拍检测；
- BPM 估计；
- AI 时序模型；
- 稳定连续控制；
- 消除单帧抖动；
- 计算轨迹和能量。

---

# 18. `window_features.window`

```json
{
  "window_id": 1254,
  "start_timestamp_ns": 153481500000000,
  "end_timestamp_ns": 153482300000000,
  "center_timestamp_ns": 153481900000000,
  "duration_ms": 800,
  "hop_ms": 100
}
```

## 18.1 `window_id`

当前窗口序号，用于检测窗口丢失和关联结果。

## 18.2 `start_timestamp_ns`

窗口起始时间。

## 18.3 `end_timestamp_ns`

窗口结束时间，通常对应最新融合帧时间。

## 18.4 `center_timestamp_ns`

窗口中心时间，用于训练标签和时间轴对齐。

## 18.5 `duration_ms`

理论窗口长度，默认 800 ms。

## 18.6 `hop_ms`

相邻窗口移动步长，默认 100 ms，因此每秒约输出 10 个窗口。

---

# 19. `window_features.source_summary`

```json
{
  "camera_frame_count": 24,
  "camera_expected_count": 24,
  "camera_missing_ratio": 0.0,
  "left_ble_sample_count": 20,
  "right_ble_sample_count": 20,
  "mean_sync_error_ms": 8.1,
  "max_sync_error_ms": 18.7
}
```

## 19.1 `camera_frame_count`

实际参与窗口计算的摄像头帧数。

## 19.2 `camera_expected_count`

按窗口长度和目标帧率计算的理论帧数。例如：

```text
800 ms × 30 FPS ≈ 24 帧
```

## 19.3 `camera_missing_ratio`

窗口内摄像头缺失比例；过高时窗口应判定无效。

## 19.4 `left_ble_sample_count`

窗口内左手 BLE 样本数。

## 19.5 `right_ble_sample_count`

窗口内右手 BLE 样本数。

## 19.6 `mean_sync_error_ms`

窗口内同步误差平均值，反映整体同步质量。

## 19.7 `max_sync_error_ms`

窗口内最大同步误差，防止平均值掩盖偶发严重错误。

---

# 20. `window_features.camera_features`

每只手包含最近窗口内视觉动态统计。

## 20.1 `trajectory_length`

手腕在窗口内运动路径总长度，用于区分大幅挥动和小幅抖动。

## 20.2 `displacement`

起点到终点的净位移。画圆时轨迹长度可能很大，但净位移很小。

## 20.3 `mean_wrist_speed`

窗口内平均手腕速度。

## 20.4 `max_wrist_speed`

窗口内最大手腕速度，适合检测快速挥拍。

## 20.5 `mean_wrist_acceleration`

窗口内平均视觉加速度。

## 20.6 `vertical_range`

手腕垂直方向最大范围，用于描述上下挥动幅度。

## 20.7 `horizontal_range`

手腕水平方向最大范围，用于描述左右摆动幅度。

## 20.8 `direction_changes`

运动方向改变次数，适合判断转折和周期动作。

## 20.9 `mean_openness`

窗口内平均手掌张开程度。

## 20.10 `openness_change`

窗口起止时手掌开合变化，适合识别张手和握拳过程。

---

# 21. `window_features.microbit_features`

每只手包含窗口内 IMU 统计。

## 21.1 `mean_acceleration_magnitude_g`

窗口内合加速度平均值；静止时通常接近 1 g。

## 21.2 `std_acceleration_magnitude_g`

合加速度波动程度，越大表示动作越剧烈或越不稳定。

## 21.3 `max_acceleration_magnitude_g`

最大冲击强度，可用于检测强拍。

## 21.4 `mean_linear_magnitude_g`

去重力后线性运动平均强度。

## 21.5 `max_linear_magnitude_g`

窗口内最大线性运动加速度。

## 21.6 `rms_linear_magnitude_g`

线性加速度均方根，反映整体动作强度，比单一峰值更稳定。

## 21.7 `motion_energy`

窗口内动作能量，通常由线性加速度平方平均计算。

## 21.8 `mean_jerk_g_s`

平均加速度变化率。

## 21.9 `max_jerk_g_s`

最大突变程度，对突然停止和击拍敏感。

## 21.10 `peak_count`

窗口内检测到的动作峰值数量，可用于节拍和重复动作判断。

## 21.11 `peak_timestamps_ns`

所有峰值时间，用于计算峰值间隔和 BPM。

## 21.12 `dominant_frequency_hz`

窗口内主要运动频率，可反映周期性挥动速度。

## 21.13 `mean_pitch_deg`、`std_pitch_deg`

Pitch 平均值和波动，用于描述手腕俯仰姿态。

## 21.14 `mean_roll_deg`、`std_roll_deg`

Roll 平均值和波动，用于描述横向倾斜变化。

---

# 22. `window_features.cross_modal_features`

## 22.1 `left_visual_imu_correlation`

左手视觉运动强度与左 micro:bit 运动强度的相关性。

## 22.2 `right_visual_imu_correlation`

右手视觉与右 micro:bit 的相关性。

## 22.3 `left_right_motion_correlation`

左右手动作的一致程度，双手同步挥动时较高。

## 22.4 `visual_imu_peak_offset_ms`

视觉动作峰值与 IMU 峰值的时间差，可评估同步准确度。

## 22.5 `beat_interval_ms`

相邻节拍峰值间隔，用于计算 BPM。

## 22.6 `estimated_bpm`

计算：

```text
BPM = 60000 / beat_interval_ms
```

只有检测到至少两个有效峰值时才可靠。

## 22.7 `combined_motion_intensity`

多模态综合运动强度，用于音乐力度和 LED 强度。

---

# 23. `window_features.quality`

```json
{
  "valid": true,
  "window_coverage_ratio": 0.97,
  "reason": null
}
```

## 23.1 `valid`

表示当前窗口是否可用于模型和控制。

## 23.2 `window_coverage_ratio`

实际有效数据覆盖比例。

推荐：

```text
< 0.8：无效
0.8～0.9：低可信
> 0.9：正常
```

## 23.3 `reason`

无效原因示例：

```text
window_not_filled
camera_missing
left_ble_missing
right_ble_missing
sync_error_too_large
insufficient_samples
```

---

# 24. `control_event` 的作用

## 24.1 定义

`control_event` 表示：

> 树莓派或 PC 已经确认的离散动作事件或控制事件。

它不是原始数据，而是高级语义结果。

## 24.2 主要用途

- 音乐重音；
- BPM 更新；
- 乐器组切换；
- LED 脉冲；
- 动作开始或停止；
- 用户界面事件提示。

## 24.3 为什么不直接使用 `window_features`

一次真实动作可能出现在多个重叠窗口中。`control_event` 经过：

```text
模型或规则
阈值判断
状态机
去重
冷却时间
```

后，只生成一次明确事件。

---

# 25. `control_event` 字段

```json
{
  "event_id": "event-00831",
  "event": {},
  "music_control": {},
  "led_control": {}
}
```

## 25.1 `event_id`

作用：

- 唯一标识一次事件；
- 防止 PC 重复执行；
- 用于 ACK 和日志关联。

## 25.2 `event.type`

可能值：

```text
downbeat
left_wrist_strike
right_wrist_strike
bilateral_strike
gesture_start
gesture_end
stop
resume
```

作用：表示事件语义。

## 25.3 `event.hand`

可能值：

```text
left
right
both
none
```

表示主导手。

## 25.4 `event.confidence`

作用：

- 模型或规则对事件判断的置信度；
- PC 可根据阈值决定是否执行。

## 25.5 `event.strength`

作用：

- 动作力度；
- 与事件置信度不同；
- 一个事件可以置信度高但力度弱。

---

# 26. `music_control`

```json
{
  "estimated_bpm": 118.1,
  "tempo_delta": 0.12,
  "volume": 0.73,
  "intensity": 0.81,
  "articulation": 0.58
}
```

## 26.1 `estimated_bpm`

当前目标 BPM，PC 用于调节播放速度或音乐节拍。

## 26.2 `tempo_delta`

相对当前 BPM 的变化量，通常取值 `[-1,1]`；正值加速，负值减速。

## 26.3 `volume`

音量控制，通常取值 `[0,1]`。

## 26.4 `intensity`

音乐力度或整体能量，可同时影响音量、动态范围、LED 亮度和乐器层数。

## 26.5 `articulation`

演奏法连续程度：

```text
0：短促、断奏
1：连贯、连奏
```

---

# 27. `led_control`

```json
{
  "pattern": "right_pulse",
  "brightness": 0.25,
  "duration_ms": 120
}
```

虽然 LED 由树莓派直接控制，该字段仍可发送给 PC，用于：

- PC 界面显示当前 LED 状态；
- 记录 LED 行为；
- 调试 LED 映射；
- 允许 PC 下发模式配置。

## 27.1 `pattern`

动画类型示例：

```text
left_pulse
right_pulse
bilateral_pulse
wave
breathing
clear
```

## 27.2 `brightness`

LED 亮度。两块 WS2812B 8×32 灯板建议限制在 `0～0.25` 或 `0～0.30`。

## 27.3 `duration_ms`

动画持续时间，适合节拍脉冲。

---

# 28. `status` 的作用

## 28.1 定义

`status` 表示：

> 当前系统是否正常工作，以及各设备、同步、网络、性能和 LED 的健康状态。

它不直接描述用户动作。

## 28.2 主要用途

- PC 状态面板；
- 断线告警；
- 性能监控；
- 丢包监控；
- 自动重连；
- 故障日志。

---

# 29. `status.camera`

```json
{
  "connected": true,
  "configured_fps": 30,
  "actual_fps": 29.4,
  "dropped_frames": 3,
  "last_frame_age_ms": 18.2,
  "processing_latency_ms": 12.4
}
```

| 字段 | 作用 |
|---|---|
| `connected` | 摄像头是否连接 |
| `configured_fps` | 配置帧率 |
| `actual_fps` | 实际处理帧率 |
| `dropped_frames` | 丢帧数量 |
| `last_frame_age_ms` | 最近一帧距当前时间 |
| `processing_latency_ms` | 视觉处理耗时 |

---

# 30. `status.microbits`

每只手分别报告：

```json
{
  "device_id": "MB_LEFT",
  "transport": "ble",
  "connected": true,
  "rssi_dbm": -58,
  "sample_rate_hz": 24.8,
  "recent_loss_ratio": 0.01,
  "clock_ready": true,
  "sync_rtt_ms": 11.2,
  "last_sample_age_ms": 28.5
}
```

| 字段 | 作用 |
|---|---|
| `device_id` | 逻辑设备 ID |
| `transport` | 当前传输方式 |
| `connected` | BLE 是否连接 |
| `rssi_dbm` | BLE 信号强度 |
| `sample_rate_hz` | 实际采样率 |
| `recent_loss_ratio` | 最近窗口丢包率 |
| `clock_ready` | 时钟映射是否建立 |
| `sync_rtt_ms` | 同步往返延迟 |
| `last_sample_age_ms` | 最近样本年龄 |

---

# 31. `status.network`

```json
{
  "pc_connected": true,
  "queued_messages": 2,
  "dropped_messages": 0,
  "send_rate_hz": 36.4,
  "reconnect_count": 1
}
```

| 字段 | 作用 |
|---|---|
| `pc_connected` | PC TCP 是否连接 |
| `queued_messages` | 当前发送队列长度 |
| `dropped_messages` | 因队列溢出丢弃数量 |
| `send_rate_hz` | 实际发送速率 |
| `reconnect_count` | 重连次数 |

---

# 32. `status.led`

```json
{
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
```

| 字段 | 作用 |
|---|---|
| `connected` | LED 模块是否正常 |
| `backend` | 使用的驱动库 |
| `gpio` | 数据输出 GPIO |
| `panel_count` | 灯板数量 |
| `total_leds` | LED 总数 |
| `brightness_limit` | 最大亮度限制 |
| `actual_brightness` | 当前亮度 |
| `fps` | LED 刷新率 |
| `error` | 错误信息 |

---

# 33. 树莓派内部同步融合整体流程

```text
摄像头采集线程
    │
    ├── frame_id
    ├── SensorTimestamp
    ├── image
    └── exposure
          │
          ▼
MediaPipe 手部检测
          │
          ├── 21 个关键点
          ├── 左右手
          └── 视觉特征
          │
          ▼
摄像头结果缓存
          │
          │ 以 SensorTimestamp 为融合目标
          ▼
融合模块
          ▲
          │
左右 micro:bit BLE 接收
          │
          ├── sequence
          ├── device_timestamp
          ├── acceleration
          ├── pitch
          └── roll
          │
          ▼
时钟映射
          │
          ▼
树莓派时间轴样本缓存
          │
          ▼
线性插值到摄像头时间
          │
          ▼
fused_frame
          │
          ▼
滑动窗口缓存
          │
          ▼
window_features
          │
          ▼
事件识别与状态机
          │
          ▼
control_event
```

---

# 34. 第一步：BLE 数据接收

每块 micro:bit 周期发送：

```text
sequence
device_timestamp_ms
ax
ay
az
pitch
roll
```

树莓派收到 Notification 时立即记录：

```python
pi_receive_timestamp_ns = time.monotonic_ns()
```

形成原始样本：

```text
RawBleSample
├── device_id
├── hand
├── sequence
├── device_timestamp_ms
├── pi_receive_timestamp_ns
├── ax
├── ay
├── az
├── pitch
└── roll
```

---

# 35. 第二步：设备时间映射

每块 micro:bit 独立建立：

```text
t_pi = a × t_device + b
```

处理步骤：

1. 树莓派发出 `SYNC`；
2. 记录发送时间 `t0`；
3. micro:bit 返回设备时间 `m1`；
4. 树莓派记录接收时间 `t2`；
5. 计算树莓派中点时间；
6. 获得同步点；
7. 多个同步点线性拟合；
8. 得到 `a` 和 `b`。

转换：

```python
aligned_timestamp_ns = (
    a * device_timestamp_ms * 1_000_000
    + b
)
```

---

# 36. 第三步：BLE 样本缓存

每只手维护一个按时间排序的环形缓冲：

```text
left_ble_buffer
right_ble_buffer
```

每个样本包含：

```text
aligned_timestamp_ns
sequence
ax
ay
az
pitch
roll
```

建议保存最近 5～10 秒。

---

# 37. 第四步：摄像头采集

Picamera2 获取：

```python
with picam2.captured_request() as request:
    frame = request.make_array("main")
    metadata = request.get_metadata()
```

保存：

```text
frame_id
SensorTimestamp
ExposureTime
image
```

---

# 38. 第五步：MediaPipe 处理

将：

```text
RGB 图像
+
SensorTimestamp 转换后的毫秒值
```

输入 MediaPipe。

输出：

```text
handedness
landmarks
world_landmarks
confidence
```

随后计算：

```text
palm_center
openness
joint_angles
wrist_velocity
wrist_acceleration
```

---

# 39. 第六步：选择融合目标时间

融合目标：

```python
target_timestamp_ns = camera.sensor_timestamp_ns
```

原因：

- 摄像头帧是视觉信息时间基准；
- micro:bit 采样率通常高于或接近摄像头处理帧率；
- 可将 micro:bit 数据插值到每个摄像头帧。

---

# 40. 第七步：micro:bit 插值

对于目标时间 `t`，找到：

```text
t0 <= t <= t1
```

线性插值：

```text
x(t) = x0 + [(t-t0)/(t1-t0)] × (x1-x0)
```

分别插值：

```text
ax
ay
az
pitch
roll
```

输出：

```text
raw_interpolated
nearest_sample_error_ms
bracket_span_ms
```

---

# 41. 第八步：即时特征计算

对插值后的 micro:bit 数据计算：

```text
acceleration_g
acceleration_magnitude
linear_acceleration
jerk
motion_energy
```

对视觉数据计算：

```text
wrist_velocity
wrist_acceleration
openness
motion_direction
```

---

# 42. 第九步：跨模态关联

按手侧匹配：

```text
camera left hand ↔ MB_LEFT
camera right hand ↔ MB_RIGHT
```

计算：

```text
视觉速度峰值
IMU 加速度峰值
峰值时间差
运动强度相关性
```

形成：

```text
cross_modal_features
```

---

# 43. 第十步：生成 `fused_frame`

当以下条件满足时生成有效帧：

```text
摄像头帧有效
至少一个手部有效
对应 micro:bit 时钟已同步
插值成功
同步误差未超过阈值
```

如果部分来源缺失，也可以继续发送消息，但将相应 `valid=false`，便于 PC 知道数据不完整的原因。

---

# 44. 第十一步：滑动窗口缓存

所有有效 `fused_frame` 加入滑动窗口缓冲。

示例：

```text
窗口长度：800 ms
步长：100 ms
```

窗口中通常包含：

```text
约 24 个摄像头帧
约 20～40 个 BLE 样本或融合帧
```

---

# 45. 第十二步：生成 `window_features`

对窗口计算：

```text
均值
标准差
最大值
最小值
RMS
能量
峰值数量
轨迹长度
方向变化
相关性
BPM
```

形成 `window_features`。

---

# 46. 第十三步：生成 `control_event`

将 `window_features` 输入：

```text
规则引擎
随机森林
LSTM
GRU
1D CNN
```

得到：

```text
gesture
confidence
continuous_controls
```

再经过：

```text
事件状态机
冷却时间
去重
阈值
```

形成唯一 `control_event`。

---

# 47. 第十四步：生成 `status`

独立状态模块每秒统计：

```text
摄像头实际 FPS
BLE RSSI
BLE 丢包
时钟同步状态
最近样本年龄
TCP 连接
队列长度
LED 状态
CPU 使用率
内存使用率
```

形成 `status`。

---

# 48. 推荐线程或任务划分

```text
Task 1：BLE 左手接收
Task 2：BLE 右手接收
Task 3：BLE 时钟同步
Task 4：摄像头采集
Task 5：MediaPipe 推理
Task 6：融合与插值
Task 7：滑动窗口特征
Task 8：事件识别
Task 9：TCP 发送
Task 10：LED 控制
Task 11：状态统计
```

BLE 部分推荐使用 `asyncio + Bleak`，摄像头和 MediaPipe 可使用独立线程或工作队列。

---

# 49. 推荐缓冲结构

```python
left_ble_buffer = deque(maxlen=500)
right_ble_buffer = deque(maxlen=500)
camera_result_buffer = deque(maxlen=120)
fused_frame_buffer = deque(maxlen=300)
event_buffer = deque(maxlen=100)
```

---

# 50. 数据缺失处理

## 50.1 摄像头缺失

```json
{
  "camera_valid": false,
  "reason": "camera_frame_missing"
}
```

可以继续输出 micro:bit 数据。

## 50.2 某一 micro:bit 缺失

```json
{
  "left_microbit_valid": false,
  "reason": "left_ble_disconnected"
}
```

可以继续使用另一只手和摄像头。

## 50.3 同步失败

```json
{
  "valid": false,
  "reason": "clock_not_ready"
}
```

## 50.4 插值失败

```json
{
  "valid": false,
  "reason": "interpolation_failed"
}
```

## 50.5 窗口未填满

```json
{
  "quality": {
    "valid": false,
    "reason": "window_not_filled"
  }
}
```

---

# 51. 推荐发送策略

## 51.1 开发和训练阶段

```text
fused_frame：25 Hz
window_features：10 Hz
control_event：事件触发
status：1 Hz
```

全部发送。

## 51.2 最终演示阶段

```text
fused_frame：5～15 Hz 或按需开启
window_features：10 Hz
control_event：事件触发
status：1 Hz
```

降低网络和 PC 解析负担。

---

# 52. 最终数据关系总结

```text
fused_frame
=
某一时刻的摄像头 + 左 micro:bit + 右 micro:bit

window_features
=
最近一段时间的多个 fused_frame 统计结果

control_event
=
根据 window_features 识别出的高级动作和控制语义

status
=
整个系统当前是否健康
```

---

# 53. 最终结论

树莓派 → PC 接口应同时保留四类数据。

## `fused_frame`

用于：

- 实时状态；
- 同步调试；
- 原始训练；
- 单帧连续控制。

## `window_features`

用于：

- 动态动作识别；
- BPM；
- 时序 AI；
- 稳定控制。

## `control_event`

用于：

- 明确动作事件；
- 音乐控制；
- LED 控制；
- 防止重复触发。

## `status`

用于：

- 设备监控；
- BLE 质量；
- 摄像头状态；
- 网络状态；
- LED 状态；
- 故障诊断。

树莓派内部应以摄像头 `SensorTimestamp` 为主时间点，将两块 micro:bit 的 BLE 数据通过独立时钟映射和线性插值对齐，再依次生成：

```text
fused_frame
→ window_features
→ control_event
```

同时由独立状态模块生成：

```text
status
```

这套结构可以同时满足实时展示、AI 训练、音乐控制、LED 反馈和系统诊断需求。
