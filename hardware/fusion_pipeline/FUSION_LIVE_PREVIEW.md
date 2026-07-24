# 正式传输链路联合预览

本文档说明 `pi-fusion` 内置预览页面的用途和运行方式。该预览可以在树莓派正式向 PC 后端传输数据的同时运行，不再需要单独启动摄像头预览或 micro:bit 预览。

## 当前推荐方式

推荐使用正式服务内置预览：

```text
pi-fusion.service
├─ 摄像头采集 + MediaPipe
├─ ESP32 UDP:17778 接收 micro:bit 广播数据
├─ micro:bit 序列检查与降噪
├─ 摄像头帧与 micro:bit 样本时间对齐
├─ TCP:9000 发送到 PC 后端
└─ HTTP:8790 提供网页预览
```

该方式只打开一次摄像头，只绑定一次 UDP `17778`，因此可以和正式 PC 后端传输同时进行。

## 页面地址

启动正式服务后，在 PC 浏览器打开：

```text
http://192.168.43.221:8790/
```

如果树莓派 IP 发生变化，将 `192.168.43.221` 替换为当前 Pi 地址。

## 可选视频流

`8790` 页面已经包含摄像头 MJPEG 预览、micro:bit 原始数据、过滤后数据以及即将发送给 PC 后端的融合数据。远端同步来的 `video_stream` 功能保留为单独的轻量摄像头调试入口，默认端口为 `8791`，由 `hardware/fusion_pipeline/video_stream.py` 提供。

该视频流在 `pi-fusion` 进程内部复用摄像头帧，不会二次占用摄像头。日常验证优先使用 `8790` 联合预览；只有在需要单独观察摄像头画面时，才在 `config.yaml` 中开启：

```yaml
video_stream:
  enabled: true
  host: "0.0.0.0"
  port: 8791
```

## 启动方式

在树莓派上启动正式链路：

```bash
sudo systemctl restart pi-fusion
sudo journalctl -u pi-fusion -f
```

只要 `hardware/fusion_pipeline/config.yaml` 中开启：

```yaml
preview:
  enabled: true
  host: "0.0.0.0"
  port: 8790
  jpeg_quality: 70
  jpeg_every_n_frames: 2
```

`pi-fusion` 就会同时提供网页预览。

## 页面展示内容

### 摄像头视频帧

页面左上角显示同一摄像头线程产生的 MJPEG 视频流。该视频流不会重新打开摄像头，也不会影响发送给 PC 后端的数据结构。

视频帧中会尽量叠加 MediaPipe 手部骨架，用于确认：

- 摄像头画面是否稳定；
- 手是否进入画面；
- MediaPipe 是否识别到手；
- 左右手关键点是否持续刷新。

为降低对正式链路的影响，预览默认每 2 帧编码 1 张 JPEG，质量为 70。需要更流畅画面时可将 `jpeg_every_n_frames` 改为 `1`；如果 Pi 负载过高，可改为 `3` 或 `4`。

### 摄像头 MediaPipe 数据

页面显示最近摄像头帧的完整数据摘要，包括：

- `frame_id`
- `ts_ns`
- `hands_detected`
- `raw_hands_detected`
- `hand_detection_rate_5s`
- `consecutive_missed_frames`
- `preview_interpolated_hands`
- `processing_latency_ms`
- `clock_ready`
- `hands`
- `landmarks_normalized`
- `world_landmarks`
- `features`

如果 `hands=[]`，说明当前帧没有检测到手，发送给 PC 的 `fused_frame.camera.hands` 也会为空。

视频骨架允许对最多 4 个连续漏检帧沿用上次结果，以减少视觉闪断。页面中的 `preview held` 表示当前使用了多少只短时保持手。该保持只影响视频叠加，不进入 `camera.hands`，也不会作为真实训练关键点发送到 PC。

发送到 PC 的 `fused_frame.camera.detection_quality` 会附带 `hand_detection_rate_5s`、`consecutive_missed_frames` 和 `preview_interpolated_hands`，用于后端记录和训练前质量筛选。

页面中的 `confidence`/`handedness_confidence` 是左右手分类置信度，不是 MediaPipe 检测置信度。摄像头颜色通道、阈值和漏检指标的详细说明见 `hardware/fusion_pipeline/CAMERA_MEDIAPIPE_TUNING.md`。

### micro:bit 刚采集/刚解码数据

该区域显示 ESP32 UDP 包到达 Pi 后，刚完成协议解码、尚未经过降噪滤波的数据。

每只手分别展示：

- `source`
- `sample_sequence`
- `device_timestamp_ms`
- `pi_rx_monotonic_ns`
- `raw.ax_mg / raw.ay_mg / raw.az_mg`
- `raw.pitch_deg / raw.roll_deg`
- `gateway.ble_rssi`
- `gateway.gateway_sequence`

这一层用于判断 micro:bit 到 ESP32 再到 Pi 的数据是否真实到达、左右手是否都在刷新。

### micro:bit 降噪过滤后数据

该区域显示正式融合缓冲实际使用的数据。

重点观察：

- `filtered`
- `outlier_detected`
- `sequence_status`
- `missing_sample_count`
- `ax_mg / ay_mg / az_mg`
- `pitch_deg / roll_deg`

如果原始样本刷新，但过滤后样本不刷新，通常表示样本被序列检查判定为重复、乱序或无效。

### 正式发送给 PC 前的完整消息

该区域显示正式链路调用 TCP 发送前的完整 JSON。它不是模拟数据，而是与 PC 后端接收的数据同源。

消息类型包括：

- `fused_frame`：摄像头帧触发的融合训练数据；
- `control_event`：micro:bit 按键事件，快速路径发送；
- `status`：系统状态，默认 1 Hz。

训练数据主要看 `fused_frame`：

```json
{
  "type": "fused_frame",
  "camera": {
    "hands": []
  },
  "microbits": [
    {
      "hand": "left",
      "available": true,
      "ax_mg": 0,
      "ay_mg": 0,
      "az_mg": 0
    },
    {
      "hand": "right",
      "available": true,
      "ax_mg": 0,
      "ay_mg": 0,
      "az_mg": 0
    }
  ],
  "fusion_quality": {
    "max_time_delta_ms": 0.0,
    "missing_sources": []
  }
}
```

如果 `microbits[].available=false`，说明当前摄像头帧附近没有找到足够接近的 micro:bit 样本。重点查看：

- 原始 micro:bit 样本是否持续刷新；
- 过滤后 micro:bit 样本是否持续刷新；
- `time_delta_ms` 是否超过 `fusion.max_age_ms`；
- `fusion_quality.missing_sources` 是否长期包含 `left_microbit` 或 `right_microbit`。

## 与旧预览页面的关系

旧预览仍保留，但只建议用于单项排查：

- `8765` 摄像头预览：只看摄像头画面和 MediaPipe。
- `8787` micro:bit 预览：只看 micro:bit 到 Pi 的实时数据。
- `8790` 正式链路联合预览：同时看摄像头、micro:bit、融合后发送前数据，并且可以和 PC 后端传输同时运行。

注意：`8765` 和 `8787` 旧预览会占用摄像头或 UDP `17778`，不能和正式 `pi-fusion` 同时运行。`8790` 内置预览可以和正式传输同时运行。

## 独立预览备用入口

仓库中仍保留：

```text
hardware/fusion_pipeline/live_preview.py
```

它用于不连接 PC 后端时单独调试融合链路。使用时需要先停止正式服务：

```bash
sudo systemctl stop pi-fusion
cd ~/aiot_conductor/project/hardware/fusion_pipeline
../../camera_to_Pi/.venv/bin/python live_preview.py --config config.yaml --host 0.0.0.0 --port 8790
```

日常实验优先使用正式服务内置预览，不建议同时运行独立预览和 `pi-fusion`。

## 验证标准

一次完整可用的正式链路预览应满足：

1. 页面顶部显示 `pi-fusion running`；
2. PC 状态显示 `connected` 或队列数持续变化；
3. 摄像头视频帧稳定刷新；
4. 摄像头 `frame_id` 持续增长；
5. 左右 micro:bit 原始样本都持续刷新；
6. 左右 micro:bit 过滤后样本都持续刷新；
7. 最新 `fused_frame.microbits[]` 中左右手尽量为 `available=true`；
8. 手进入画面后，`camera.hands[]` 中出现 `landmarks_normalized` 和 `world_landmarks`；
9. `fusion_quality.missing_sources` 不应长期包含同一个传感器。

## 常见问题

### 页面打不开

先确认正式服务是否在运行：

```bash
systemctl status pi-fusion
```

确认端口是否监听：

```bash
ss -ltnp | grep ':8790'
```

### 页面打开但摄像头视频不动

查看服务日志：

```bash
sudo journalctl -u pi-fusion -f
```

常见原因：

- 摄像头初始化失败；
- MediaPipe 初始化失败；
- OpenCV 不可用，导致 JPEG 预览被禁用；
- Pi 负载过高，视频编码被拖慢。

如果只是 OpenCV 不可用，正式数据链路仍可能正常，只是视频预览不可用。

### 正式发送数据正常，但页面刷新慢

降低预览压力：

```yaml
preview:
  jpeg_quality: 60
  jpeg_every_n_frames: 3
```

修改后重启：

```bash
sudo systemctl restart pi-fusion
```

### PC 后端未连接

页面顶部 PC 状态会显示 `offline`。这只表示 TCP 后端没有连上，不代表 Pi 端采集失败。可以继续用页面检查摄像头和 micro:bit 是否正常。

