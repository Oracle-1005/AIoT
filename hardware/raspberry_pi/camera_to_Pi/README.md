# Camera → Raspberry Pi 采集与手部关键点 Demo

本工程依据 `Camera_to_Pi_v01(2).md` 实现摄像头链路的前三层，并为后续去噪和多传感器时间同步保留稳定接口。

## 1. 当前实现

```text
OV5647 / CSI
  → Picamera2 同一 request 获取 image + metadata
  → 最大 2 帧 latest-frame 队列，积压时丢弃最旧帧
  → MediaPipe Hand Landmarker（VIDEO 模式）
  → 左/右手、handedness_score、21 个 image/world landmarks
  → 有效性检查、标签稳定、跳点标记、EMA、短时缺失保持
  → CameraClockMapper 映射到 Pi monotonic 时间轴
  → JSON Lines camera_landmark_frame
```

原始图像只在树莓派内存中使用，不写入 JSON，也不持续发送给 PC。

## 2. 安装

建议使用 64 位 Raspberry Pi OS Bookworm 或更新版本。

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-venv curl

cd camera_to_pi_demo
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
./download_model.sh
```

先验证摄像头：

```bash
rpicam-hello --list-cameras
rpicam-hello --timeout 3000
```

## 3. 运行

持续输出 JSONL 到终端：

```bash
python main.py --config config.json
```

采集 100 帧并写文件：

```bash
python main.py --config config.json --max-frames 100 --output output/camera.jsonl
```

调试单帧结构：

```bash
python main.py --config config.json --max-frames 1 --pretty
```

## 4. 重要配置

### 像素顺序

Picamera2 的 `RGB888` NumPy 数组实际按 `[B,G,R]` 排列，因此配置中保持：

```json
"pixel_format": "RGB888",
"input_array_order": "BGR"
```

检测器会在交给 MediaPipe 前转换为真正的 SRGB。

### 左右手校准

不同安装方向和是否镜像会影响左右手标签。先保持：

```json
"horizontal_flip": false,
"swap_handedness_labels": false
```

让用户分别只举左手和右手检查输出。如果标签相反，只将 `swap_handedness_labels` 改为 `true`；如果画面本身需要镜像，再改 `horizontal_flip`，不要同时无依据地修改两项。

## 5. 置信度的实现

MediaPipe Hand Landmarker 在初始化时使用三类阈值：

- `min_hand_detection_confidence`：手掌检测阈值；
- `min_hand_presence_confidence`：关键点模型判断手存在的阈值；
- `min_tracking_confidence`：连续帧跟踪阈值。

逐手直接输出的是 `handedness_score`，表示 Left/Right 分类置信度。Hand Landmarker 并不逐关键点输出一个可直接使用的置信度，因此工程另外生成：

- `detection_valid`：21 点完整、数值有限、点大多在画面内、左右手置信度达标、未发生被拒绝的大跳点；
- `quality_score`：`handedness_score × 画面内关键点比例 × 跳点惩罚`，是工程质量分，不是 MediaPipe 原始检测概率；
- `quality_flags`：低置信度、越界、异常跳点、短时补点等原因。

## 6. 去噪对接

当前入口为：

```python
LandmarkNoiseProcessor.process(raw_hands, timestamp_ns)
```

当前实现是轻量 EMA、跳点拒绝和最多 2 帧短时保持。之后替换为 One-Euro、Kalman 或按手腕速度自适应滤波时，保持输入和输出数据类不变即可，不需要修改 Picamera2、MediaPipe 或同步模块。

注意：`source="held"` 或 `source="jump_rejected"` 的点可以用于界面连续显示，但 `detection_valid=false`，不应被 PC 端当作高质量训练样本。

## 7. 时间同步对接

每帧保留三类时间：

- `sensor_timestamp_ns`：摄像头元数据 `SensorTimestamp`；
- `pi_frame_received_ns`：Python 取得该帧时的 `time.monotonic_ns()`；
- `pi_aligned_timestamp_ns`：`CameraClockMapper` 映射后的 Pi 统一时间。

当前映射器对 `pi_received - sensor_timestamp` 做滑动窗口中位数，只估计时钟偏移。后续若发现漂移，可在 `CameraClockMapper.update()` 内改为线性回归：

```text
pi_time = scale × sensor_time + offset
```

下游仍只读取 `pi_aligned_timestamp_ns`，因此接口不变。双 micro:bit 也应各自实现同样的 Mapper，最后由 `SensorSynchronizer` 按统一 Pi 时间选择最近样本或插值，组成 `FusedSensorFrame`。

## 8. JSONL 核心字段

```json
{
  "type": "camera_landmark_frame",
  "frame_sequence": 12,
  "sensor_timestamp_ns": 123,
  "pi_frame_received_ns": 456,
  "pi_aligned_timestamp_ns": 450,
  "camera": {
    "hands_detected": 2,
    "hands_output": 2,
    "hands": [
      {
        "hand_label": "left",
        "handedness_score": 0.97,
        "image_landmarks": [],
        "world_landmarks": [],
        "detection_valid": true,
        "quality_score": 0.95,
        "quality_flags": [],
        "source": "detected"
      }
    ]
  }
}
```

## 9. 静态测试

无需摄像头即可测试滤波与时钟映射：

```bash
python -m unittest discover -s tests
```
