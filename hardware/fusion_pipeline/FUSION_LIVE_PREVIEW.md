# 摄像头、micro:bit 与融合发送前数据联合预览

本文档说明 `hardware/fusion_pipeline/live_preview.py` 的用途和运行方式。该预览用于调试完整硬件链路中的三个关键阶段：

1. 摄像头刚采集并经过 MediaPipe 后的手部关键点数据；
2. ESP32 转发到树莓派后，micro:bit 刚解码出的原始 IMU 样本；
3. 经过序列检查、降噪、时间对齐和融合后，即将发送给 PC 后端的完整 JSON 消息。

## 与已有预览页面的关系

之前已有两个独立预览：

- 摄像头预览：`hardware/raspberry_pi/camera_to_Pi/visual_verify.py`，默认端口 `8765`，用于观察摄像头画面和 MediaPipe 手部识别效果。
- micro:bit 预览：`hardware/microbit/microbit_to_pi/tools/live_preview_server.py`，默认端口 `8787`，用于观察左右 micro:bit 的实时 IMU 和按键事件。

新的联合预览不是替代这两个页面，而是把“正式融合链路”中的数据阶段集中展示：

- 如果只想看摄像头画面是否正常，用 `8765` 摄像头预览。
- 如果只想看左右 micro:bit 是否稳定到达 Pi，用 `8787` micro:bit 预览。
- 如果要确认训练数据最终是否完整、时间同步是否成功、发送给 PC 前的 `fused_frame` 是否正确，用本文档的联合预览，默认端口 `8790`。

联合预览不会连接 PC 后端，也不会向 PC 发送数据。页面中的“整理后即将发送给 PC 的完整消息”表示正式 `pi-fusion` 服务中调用 TCP 发送前的同结构 JSON。

## 互斥关系

联合预览会占用：

- 摄像头设备；
- ESP32 到 Pi 的 UDP 端口 `17778`；
- 预览网页端口 `8790`。

因此运行联合预览前，应先停止正式融合服务和其他占用摄像头或 `17778` 的预览：

```bash
sudo systemctl stop pi-fusion
pkill -f visual_verify.py || true
pkill -f live_preview_server.py || true
```

如果 `pi-fusion` 正在运行，联合预览可能无法绑定 UDP `17778`，或者摄像头初始化失败。

## 运行方式

在树莓派上进入统一项目目录：

```bash
cd ~/aiot_conductor/project/hardware/fusion_pipeline
../../camera_to_Pi/.venv/bin/python live_preview.py --config config.yaml --host 0.0.0.0 --port 8790
```

如果当前虚拟环境已激活，也可以使用：

```bash
python live_preview.py --config config.yaml --host 0.0.0.0 --port 8790
```

在 PC 浏览器打开：

```text
http://192.168.43.221:8790/
```

如果树莓派 IP 发生变化，把 `192.168.43.221` 替换为当前 Pi 地址。

## 页面展示内容

### 摄像头最新采集与 MediaPipe 输出

该区域显示最近一帧摄像头数据：

- `frame_id`：摄像头帧序号；
- `ts_ns`：转换到 Pi 单调时钟后的时间戳；
- `hands_detected`：当前帧检测到的手数量；
- `clock_ready`：摄像头时间映射是否已经稳定；
- `processing_latency_ms`：摄像头采集加 MediaPipe 处理耗时；
- `hands`：完整手部数据，包括 `landmarks_normalized`、`world_landmarks` 和特征字段。

如果 `hands=[]`，说明当前画面没有被 MediaPipe 检出手部，后续发送前数据中也不会有手部关键点。

### micro:bit 刚解码原始样本

该区域显示 ESP32 UDP 包到达 Pi 后，刚完成协议解码、尚未经过降噪滤波的样本。

每只手分别展示：

- `source`：`left` 或 `right`；
- `sample_sequence`：micro:bit 样本序号；
- `device_timestamp_ms`：micro:bit 本机时间；
- `pi_rx_monotonic_ns`：Pi 收到该 UDP 包时的单调时钟时间；
- `raw.ax_mg / ay_mg / az_mg`：原始加速度；
- `raw.pitch_deg / roll_deg`：原始姿态角；
- `gateway.ble_rssi`：ESP32 扫描到该 micro:bit 广播时的 RSSI；
- `gateway.gateway_sequence`：ESP32 网关帧序号。

这一层用于判断 ESP32 到 Pi 的 micro:bit 数据是否真的到达、频率是否稳定、左右手是否都在刷新。

### micro:bit 过滤后进入融合缓冲的样本

该区域显示经过序列检查和噪声过滤后的样本，也就是正式融合缓冲实际使用的数据。

重点观察：

- `filtered=true`；
- `outlier_detected` 是否频繁为 `true`；
- `sequence_status` 是否经常为 `sequence_gap`；
- `missing_sample_count` 是否持续增长；
- `ax_mg / ay_mg / az_mg` 与原始样本相比是否明显被平滑。

如果原始样本在刷新，但过滤后样本不刷新，通常说明样本被序列跟踪器判定为重复、乱序或无效。

### 整理后即将发送给 PC 的完整消息

该区域显示最新一条发送前消息，类型可能是：

- `fused_frame`：摄像头触发的数据融合帧；
- `control_event`：micro:bit 按键事件，快速路径发送；
- `status`：系统状态，默认 1 Hz。

训练数据主要来自 `fused_frame`：

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

如果 `microbits[].available=false`，说明该摄像头帧附近没有找到足够接近的 micro:bit 样本。需要重点查看：

- 原始 micro:bit 样本是否持续刷新；
- 过滤后样本是否持续刷新；
- `time_delta_ms` 是否超过 `fusion.max_age_ms`；
- `fusion_quality.missing_sources` 中是否有 `left_microbit` 或 `right_microbit`。

## 验证标准

一次可用的完整链路预览应满足：

1. 摄像头区域 `frame_id` 持续增长；
2. 左右 micro:bit 原始样本都持续刷新；
3. 左右 micro:bit 过滤后样本都持续刷新；
4. 最新 `fused_frame.microbits[]` 中左右手尽量为 `available=true`；
5. 当手进入画面时，`camera.hands[]` 中出现 `landmarks_normalized` 和 `world_landmarks`；
6. `fusion_quality.missing_sources` 不应长期包含同一个传感器。

## 常见问题

### 页面能打开，但摄像头没有数据

可能是正式服务或旧摄像头预览仍占用摄像头。先执行：

```bash
sudo systemctl stop pi-fusion
pkill -f visual_verify.py || true
```

然后重新启动联合预览。

### micro:bit 原始样本有数据，但发送前 `available=false`

这说明 micro:bit 数据确实到达了 Pi，但时间对齐失败。常见原因是样本离摄像头帧时间太远，超过了 `config.yaml` 中的：

```yaml
fusion:
  max_age_ms: 120
```

调试阶段可以临时改为 `300` 或 `500`，先确认数据链路完整，再逐步收紧时间同步要求。

### 原始样本不刷新

优先检查：

- ESP32 网关是否连上 Wi-Fi；
- ESP32 是否正在扫描到两个 micro:bit；
- micro:bit 是否烧录为广播方案；
- Pi 上是否有其他程序占用 UDP `17778`。

### 按键事件如何看

按键事件不会等待摄像头帧融合，会作为 `control_event` 直接出现在“整理后即将发送给 PC 的完整消息”和“最近发送前消息队列”中。

## 恢复正式链路

预览完成后按 `Ctrl+C` 停止联合预览，然后恢复正式服务：

```bash
sudo systemctl start pi-fusion
sudo journalctl -u pi-fusion -f
```

