# 摄像头可视预览与后续融合接口说明

本文档说明 `camera_to_Pi` 工程中如何打开摄像头采集、如何进行浏览器可视预览，以及后续树莓派侧需要为摄像头关键点降噪、双 micro:bit 时间同步和多源数据整合预留的数据输出方式。

## 1. 运行环境

当前工程统一使用同一个虚拟环境：

```bash
cd ~/aiot_conductor/project/camera_to_Pi
source .venv/bin/activate
```

该虚拟环境已经用于以下链路：

- CSI 摄像头采集：`picamera2`
- 手部关键点识别：`mediapipe-nightly`
- 图像处理和可视化：`opencv`
- micro:bit BLE 接收：`bleak`

后续 micro:bit -> Pi、camera -> Pi、Pi -> PC 三段链路都应继续在这个 `.venv` 中运行，避免多个 Python 环境之间出现依赖不一致。

## 2. 摄像头硬件检查

先确认树莓派识别到 CSI 摄像头：

```bash
rpicam-hello --list-cameras
```

当前设备应能看到类似输出：

```text
0 : ov5647 [2592x1944 10-bit GBRG]
```

短时间预览：

```bash
rpicam-hello --timeout 3000
```

持续预览：

```bash
rpicam-hello --timeout 0
```

这些命令只验证摄像头和 libcamera 链路，不验证 MediaPipe。

## 3. 命令行采集与识别验证

进入工程目录并激活虚拟环境：

```bash
cd ~/aiot_conductor/project/camera_to_Pi
source .venv/bin/activate
```

验证 MediaPipe 模型文件存在：

```bash
ls -lh models/hand_landmarker.task
```

如果模型缺失，下载固定版本模型：

```bash
bash download_model.sh
```

运行单帧采集和识别，输出一帧 JSON：

```bash
python main.py --config config.json --max-frames 1 --pretty
```

连续采集 100 帧并写入 JSON Lines 文件：

```bash
python main.py --config config.json --max-frames 100 --output output/camera.jsonl
```

持续向终端输出：

```bash
python main.py --config config.json
```

输出中 `camera.hands_detected=0` 不代表摄像头失败，只表示该帧没有检测到手。摄像头失败通常表现为长时间没有新帧、`TimeoutError`，或 `rpicam-hello --list-cameras` 无法识别设备。

## 4. 浏览器可视预览

工程中提供了 `visual_verify.py`，用于浏览器实时查看摄像头画面、手部骨架、FPS、延迟、丢帧数和时钟状态。

启动可视预览服务：

```bash
cd ~/aiot_conductor/project/camera_to_Pi
source .venv/bin/activate
python visual_verify.py --config config.json --host 0.0.0.0 --port 8765
```

后台启动方式：

```bash
cd ~/aiot_conductor/project/camera_to_Pi
nohup .venv/bin/python visual_verify.py --config config.json --host 0.0.0.0 --port 8765 > /tmp/camera_visual_verify.log 2>&1 &
echo $! > /tmp/camera_visual_verify.pid
```

浏览器访问：

```text
http://<树莓派IP>:8765
```

当前树莓派局域网地址曾检测为：

```text
http://192.168.43.221:8765
```

如 IP 改变，可在树莓派上查看：

```bash
hostname -I
```

查看服务状态：

```bash
curl http://127.0.0.1:8765/status
```

停止后台服务：

```bash
kill $(cat /tmp/camera_visual_verify.pid)
```

查看后台日志：

```bash
tail -f /tmp/camera_visual_verify.log
```

页面中重点观察：

- `running=true`：预览服务和采集线程正在运行。
- `frames` 持续增加：摄像头采集正常。
- `clock_ready=true`：摄像头时间戳已稳定映射到 Pi 单调时间轴。
- `hands_detected`：当前帧 MediaPipe 原始检测到的手数。
- `latency_ms`：从程序取到图像帧到完成关键点输出的耗时。
- `dropped_capture_frames`：采集队列因处理速度不足丢弃的旧帧数。

如果丢帧持续快速增加，优先把 `config.json` 中的 `camera.fps` 从 `30.0` 降到 `20.0` 或 `15.0`，再做 micro:bit 和 Pi -> PC 集成。

## 5. 摄像头侧当前输出

`main.py` 当前输出类型为：

```text
camera_landmark_frame
```

示例结构：

```json
{
  "type": "camera_landmark_frame",
  "schema_version": "1.0",
  "frame_sequence": 12,
  "sensor_timestamp_ns": 123456789,
  "pi_frame_received_ns": 123470000,
  "pi_aligned_timestamp_ns": 123469000,
  "media_timestamp_ms": 123456,
  "processing_finished_ns": 123500000,
  "capture_to_output_latency_ns": 30000,
  "width": 640,
  "height": 480,
  "pixel_format": "RGB888",
  "metadata": {
    "exposure_time_us": 33177,
    "analogue_gain": 8.0,
    "frame_duration_us": 33304
  },
  "clock_mapping": {
    "pi_aligned_timestamp_ns": 123469000,
    "offset_ns": 12000,
    "residual_ns": 1000,
    "sample_count": 30,
    "ready": true
  },
  "dropped_capture_frames": 0,
  "camera": {
    "hands_detected": 1,
    "hands_output": 1,
    "hands": []
  }
}
```

原始图像帧只在树莓派内存中用于 MediaPipe 和可视预览，默认不写入 JSON，也不持续发送给 PC。

## 6. 树莓派侧降噪预留

摄像头关键点进入 PC 前，树莓派应先完成基础质量处理。当前 `LandmarkNoiseProcessor` 已预留并实现基础版本，后续可在不改变输出字段的前提下替换算法。

当前和后续建议保留的处理职责：

- 关键点数量检查：每只手必须有 21 个 `image_landmarks` 和 21 个 `world_landmarks`。
- 数值有效性检查：过滤 NaN、Inf 等不可用坐标。
- 画面边界检查：统计关键点是否大部分仍在图像范围内。
- 左右手标签稳定：低置信度或重复标签时，结合上一帧手腕位置重新分配。
- 异常跳点检测：手腕位置短时间大幅跳变时标记 `abnormal_jump`。
- 轻量平滑滤波：当前使用 EMA，后续可替换为 One-Euro、Kalman 或按速度自适应滤波。
- 短时缺失保持：遮挡 1-2 帧时可输出 `source="held"`，但 `detection_valid=false`。

每只手建议持续输出：

```json
{
  "hand_label": "left",
  "handedness_score": 0.97,
  "image_landmarks": [],
  "world_landmarks": [],
  "detection_valid": true,
  "quality_score": 0.95,
  "quality_flags": [],
  "source": "detected",
  "missing_frames": 0
}
```

训练数据和动作判断应优先使用：

- `detection_valid=true`
- `source="detected"`
- `quality_flags=[]` 或仅包含可接受的轻微质量提示

`source="held"` 或 `source="jump_rejected"` 可用于界面连续显示，但不应作为高质量训练样本。

## 7. micro:bit 侧输入预留

双 micro:bit 通过 BLE Notify 向树莓派发送两类包：

- `sensor_state`：25-50 Hz 周期发送，17 B。
- `control_event`：事件确认后立即重复发送，11 B。

树莓派收到 BLE Notify 后应立即记录：

```text
pi_rx_monotonic_ns = time.monotonic_ns()
```

并按包类型分流。

`sensor_state` 解析后建议输出：

```json
{
  "type": "microbit_sensor_state",
  "source": "left",
  "message_type": 1,
  "hand": 0,
  "sample_sequence": 1821,
  "device_timestamp_ms": 73452,
  "pi_rx_monotonic_ns": 48392014588712,
  "raw": {
    "ax_mg": 112,
    "ay_mg": -934,
    "az_mg": 287,
    "pitch_deg": -18,
    "roll_deg": 42
  },
  "time_alignment": null
}
```

`control_event` 解析后建议输出：

```json
{
  "type": "microbit_control_event",
  "source": "right",
  "message_type": 2,
  "hand": 1,
  "event_sequence": 215,
  "device_timestamp_ms": 82411,
  "pi_rx_monotonic_ns": 48392023511710,
  "event_code": "B_LONG_PRESS",
  "priority": 100,
  "repeat_index": 0,
  "repeat_total": 3,
  "duplicate": false,
  "mapped_candidate": "emergency_stop",
  "time_alignment": null
}
```

控制事件去重键：

```text
(source, event_sequence)
```

重复包只用于提高 BLE 送达概率，不应重复触发系统动作。

## 8. 时间同步策略

所有传感器最终必须映射到 Pi 单调时间轴，供融合模块按统一时间排序。

摄像头时间字段：

- `sensor_timestamp_ns`：Picamera2/libcamera 给出的摄像头采集时间。
- `pi_frame_received_ns`：Python 程序拿到该帧时的 Pi 单调时间。
- `pi_aligned_timestamp_ns`：映射后的统一 Pi 时间。

micro:bit 时间字段：

- `device_timestamp_ms`：micro:bit 启动后的毫秒时间，必须是采样或事件确认时刻。
- `pi_rx_monotonic_ns`：树莓派收到 BLE Notify 时立即记录的 Pi 单调时间。
- `pi_aligned_timestamp_ns`：后续由 `MicrobitClockMapper` 映射得到。

初始同步方式可使用滑动窗口偏移估计：

```text
offset = median(pi_rx_monotonic_ns - device_timestamp_ms * 1_000_000)
pi_aligned_timestamp_ns = device_timestamp_ms * 1_000_000 + offset
```

但 BLE 包可能被控制事件延迟，因此只有稳定周期到达的 `sensor_state` 适合更新时钟偏移。明显延迟的状态包、重复事件包和重连后的异常包不应直接用于更新偏移。

后续如果观察到设备时钟漂移，应将 mapper 升级为线性回归：

```text
pi_time = scale * device_time + offset
```

下游模块仍只读取 `pi_aligned_timestamp_ns`，因此 mapper 内部升级不影响数据接口。

## 9. 融合输出预留

Pi -> PC 建议使用 JSON Lines，每行一个完整 JSON 对象。预留三类输出：

| 类型 | 说明 | 是否表示用户动作 |
| --- | --- | --- |
| `fused_frame` | 某个统一时间点上的完整感知状态 | 是，供模型输入 |
| `control_event` | 已确认的按钮或安全事件 | 是，供系统控制 |
| `status` | 设备、网络、识别质量和健康状态 | 否 |

建议端口：

```text
9000
```

`fused_frame` 示例：

```json
{
  "type": "fused_frame",
  "schema_version": "1.0",
  "fused_sequence": 1024,
  "pi_aligned_timestamp_ns": 48392020000000,
  "sync_policy": {
    "camera_max_age_ms": 80,
    "microbit_max_age_ms": 80,
    "interpolation": "nearest_or_hold_short_gap"
  },
  "left_microbit": {
    "available": true,
    "sample_sequence": 1821,
    "device_timestamp_ms": 73452,
    "pi_rx_monotonic_ns": 48392014588712,
    "pi_aligned_timestamp_ns": 48392019880000,
    "ax_mg": 112,
    "ay_mg": -934,
    "az_mg": 287,
    "pitch_deg": -18,
    "roll_deg": 42,
    "quality_flags": []
  },
  "right_microbit": {
    "available": true,
    "sample_sequence": 1808,
    "device_timestamp_ms": 73390,
    "pi_rx_monotonic_ns": 48392014610123,
    "pi_aligned_timestamp_ns": 48392019910000,
    "ax_mg": -32,
    "ay_mg": -901,
    "az_mg": 330,
    "pitch_deg": -15,
    "roll_deg": -37,
    "quality_flags": []
  },
  "camera": {
    "available": true,
    "frame_sequence": 392,
    "sensor_timestamp_ns": 48392019600000,
    "pi_frame_received_ns": 48392020500000,
    "pi_aligned_timestamp_ns": 48392020050000,
    "hands_detected": 2,
    "hands": []
  },
  "fusion_quality": {
    "max_time_delta_ms": 14,
    "missing_sources": [],
    "dropped_camera_frames": 0,
    "left_microbit_gap": 0,
    "right_microbit_gap": 0
  }
}
```

`control_event` 上报示例：

```json
{
  "type": "control_event",
  "schema_version": "1.0",
  "event_id": "right-215",
  "source": "right_microbit",
  "pi_aligned_timestamp_ns": 48392023500000,
  "event_code": "B_LONG_PRESS",
  "mapped_action": "emergency_stop",
  "priority": 100,
  "duplicate": false
}
```

`status` 上报示例：

```json
{
  "type": "status",
  "schema_version": "1.0",
  "pi_timestamp_ns": 48392030000000,
  "camera": {
    "connected": true,
    "fps": 26.5,
    "dropped_capture_frames": 107,
    "mediapipe_loaded": true,
    "clock_ready": true
  },
  "microbit": {
    "left_connected": true,
    "right_connected": true,
    "left_clock_ready": true,
    "right_clock_ready": true
  },
  "pc_link": {
    "connected": false,
    "queued_messages": 0
  }
}
```

## 10. 集成顺序建议

1. 摄像头链路单独稳定运行：`main.py` 和 `visual_verify.py` 都能连续输出。
2. micro:bit BLE 接收单独稳定运行：左右手 `sensor_state` 25-50 Hz，`control_event` 可去重。
3. 分别实现 `CameraClockMapper`、`LeftMicrobitClockMapper`、`RightMicrobitClockMapper`。
4. 建立三个按 `pi_aligned_timestamp_ns` 排序的短窗口缓存。
5. `SensorSynchronizer` 以固定融合频率取最近样本或短时保持，生成 `fused_frame`。
6. 控制事件走快速路径，不等待摄像头或传感器融合。
7. Pi -> PC 统一发送 `fused_frame`、`control_event`、`status` 三类 JSONL。

## 11. 常见问题

### 页面能打开但没有手部骨架

确认手在画面中、光线足够、距离适中。`hands_detected=0` 只表示当前画面未识别到手。

### 页面 FPS 低或丢帧增加

先降低 `config.json`：

```json
"fps": 15.0
```

必要时再降低分辨率或只检测单手。

### MediaPipe 输出 warning

类似 `madvise(MADV_NOHUGEPAGE)`、`Feedback manager requires a model with a single signature inference` 的 warning 当前不影响推理结果。只要 `detector OK`、`frames` 增加、JSON 正常输出，即可继续集成。

### 不要把原始视频长期发给 PC

默认只发送关键点、质量标记、传感器状态和同步后的融合帧。原始图像仅用于本地可视调试、训练数据采集或错误复现。
