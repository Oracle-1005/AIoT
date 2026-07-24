# 融合预览页面与 PC 后端服务集成更新说明

本文档记录本次关于 `pi-fusion` 正式数据传输、联合预览页面和 PC 后端服务协同运行的更新内容。

## 更新目标

本次更新的目标是把原本分散的摄像头预览、micro:bit 预览和融合数据预览整合到正式 `pi-fusion` 服务内部，使树莓派可以在继续向 PC 后端传输数据的同时，提供一个统一的浏览器预览页面。

更新后的正式链路为：

```text
micro:bit L/R
  -> BLE 广播
  -> ESP32 BLE-to-Wi-Fi 网关
  -> UDP:17778
  -> Raspberry Pi pi-fusion
       -> 摄像头采集 + MediaPipe
       -> micro:bit 原始样本解码
       -> micro:bit 序列检查与降噪
       -> 摄像头帧与 micro:bit 样本时间对齐
       -> TCP:9000 发送给 PC 后端
       -> HTTP:8790 提供联合预览页面
```

## 本次主要改动

### 1. `pi-fusion` 内置 HTTP 预览服务

新增 `hardware/fusion_pipeline/preview_server.py`。

该模块在 `pi-fusion` 同一进程内启动 HTTP 服务，默认监听：

```text
0.0.0.0:8790
```

它不单独打开摄像头，也不单独绑定 ESP32 的 UDP `17778`，只读取 `pi-fusion` 已经采集到的内存状态。

页面提供：

- `/`：联合预览页面；
- `/state`：当前摄像头、micro:bit、融合输出、TCP 状态 JSON；
- `/stream`：摄像头 MJPEG 视频流。

### 2. 正式主程序接入预览状态

更新 `hardware/fusion_pipeline/main.py`。

主程序现在会在正式链路启动时同步启动预览服务：

- 摄像头帧进入融合前，会同步写入预览状态；
- micro:bit 原始样本刚解码后，会同步写入预览状态；
- micro:bit 过滤后样本进入融合缓冲前，会同步写入预览状态；
- `fused_frame`、`control_event`、`status` 在发送给 PC 后端前，会同步写入预览状态；
- TCP 客户端状态会同步显示在页面顶部。

预览服务启动失败时，正式传输不会被阻断，只会在日志中记录错误并继续运行。

### 3. 摄像头视频帧复用正式采集线程

更新：

- `hardware/sensors/camera.py`
- `hardware/fusion_pipeline/camera_adapter.py`

摄像头线程新增可选 JPEG 预览帧输出：

```yaml
preview:
  jpeg_quality: 70
  jpeg_every_n_frames: 2
```

该视频帧只用于浏览器 `/stream`，不会进入发送给 PC 后端的 `fused_frame` JSON，也不会改变训练数据结构。

默认每 2 帧编码 1 张 JPEG，降低树莓派 CPU 压力。

### 4. 保留独立联合预览备用入口

保留 `hardware/fusion_pipeline/live_preview.py`。

它仍可用于“不连接 PC 后端”的离线调试，但日常使用推荐正式服务内置预览。

注意：独立预览会占用摄像头和 UDP `17778`，不能和 `pi-fusion` 同时运行。

## 预览页面启动方法

### 推荐方式：随正式服务启动

在树莓派上执行：

```bash
sudo systemctl restart pi-fusion
sudo journalctl -u pi-fusion -f
```

然后在 PC 浏览器打开：

```text
http://192.168.43.221:8790/
```

如果树莓派 IP 发生变化，需要替换为当前 Pi 地址。

### 配置开关

配置文件：

```text
hardware/fusion_pipeline/config.yaml
```

预览相关配置：

```yaml
preview:
  enabled: true
  host: "0.0.0.0"
  port: 8790
  jpeg_quality: 70
  jpeg_every_n_frames: 2
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `enabled` | 是否启用内置预览 |
| `host` | HTTP 监听地址，`0.0.0.0` 表示允许 PC 浏览器访问 |
| `port` | 预览页面端口，默认 `8790` |
| `jpeg_quality` | 摄像头 JPEG 质量，越高越清晰但 CPU 和带宽更高 |
| `jpeg_every_n_frames` | 每隔多少帧编码一张预览图，越大负载越低 |

### PC 后端启动方法

PC 后端用于接收树莓派发来的正式 TCP 数据，默认端口：

```text
TCP:9000
HTTP API:5000
```

在 PC 项目根目录执行：

```powershell
backend\.venv\Scripts\python.exe backend\app.py
```

如果 `backend\.venv` 不存在，先执行：

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

验证后端是否可访问：

```powershell
Invoke-WebRequest http://127.0.0.1:5000/api/status
netstat -ano | findstr ":5000 :9000"
```

## 页面展示内容

`8790` 页面整合显示：

1. 摄像头视频帧；
2. 摄像头 MediaPipe 数据；
3. `landmarks_normalized`；
4. `world_landmarks`；
5. 左右 micro:bit 原始样本；
6. 左右 micro:bit 降噪过滤后样本；
7. 正式发送给 PC 后端前的完整 `fused_frame`；
8. micro:bit 按键产生的 `control_event`；
9. 系统 `status`；
10. TCP 后端连接状态。

其中训练数据主要看：

```text
latest_outbound.type == "fused_frame"
```

并重点检查：

```text
camera.hands[]
camera.hands[].world_landmarks
microbits[].available
microbits[].ax_mg / ay_mg / az_mg
fusion_quality.missing_sources
```

## 相关文件

| 文件 | 作用 |
| --- | --- |
| `hardware/fusion_pipeline/main.py` | 正式 `pi-fusion` 主程序；启动摄像头、ESP32 UDP 接收、融合、TCP 发送和内置预览 |
| `hardware/fusion_pipeline/preview_server.py` | 新增内置 HTTP 预览服务，提供 `/`、`/state`、`/stream` |
| `hardware/fusion_pipeline/config.yaml` | 配置 TCP 后端、融合参数和 `preview` 开关 |
| `hardware/fusion_pipeline/camera_adapter.py` | 将摄像头采集层输出转换为融合帧，并传递预览 JPEG |
| `hardware/sensors/camera.py` | 摄像头采集、MediaPipe HandLandmarker、`world_landmarks` 提取和预览 JPEG 编码 |
| `hardware/fusion_pipeline/gateway_adapter.py` | ESP32 UDP 数据解析；提供 micro:bit 原始样本调试回调 |
| `hardware/fusion_pipeline/live_preview.py` | 离线联合预览备用入口，不建议和正式服务同时运行 |
| `hardware/fusion_pipeline/FUSION_LIVE_PREVIEW.md` | 正式联合预览页面的日常使用说明 |
| `backend/app.py` | PC 后端 HTTP 服务入口 |
| `backend/pi_gateway.py` | PC 后端 TCP:9000 接收树莓派数据 |

## 常见问题与解决方法

### 1. 页面突然打不开

现象：

```text
http://192.168.43.221:8790/ 无法打开
```

检查：

```bash
systemctl is-active pi-fusion
ss -ltnp | grep ':8790'
sudo journalctl -u pi-fusion -n 80 --no-pager
```

可能原因：

- `pi-fusion` 未启动或启动失败；
- `8790` 端口未监听；
- `preview.enabled` 未开启；
- 部署时只同步了部分文件，导致 `main.py`、`camera_adapter.py`、`camera.py` 版本不一致。

解决：

```bash
sudo systemctl restart pi-fusion
```

如果日志中出现函数参数不匹配，例如：

```text
TypeError: CameraAdapter.__init__() got an unexpected keyword argument 'enable_preview_jpeg'
```

说明 Pi 上文件版本不同步，需要重新同步：

```text
hardware/fusion_pipeline/main.py
hardware/fusion_pipeline/camera_adapter.py
hardware/sensors/camera.py
hardware/fusion_pipeline/preview_server.py
```

### 2. `/state` 拒绝连接

现象：

```text
Connection refused
```

检查：

```bash
ss -ltnp | grep ':8790'
sudo journalctl -u pi-fusion --since '5 minutes ago' --no-pager | grep -Ei 'preview|8790|ERROR|Traceback|failed'
```

如果 `pi-fusion` 仍 active，但 `8790` 不监听，说明预览服务没有启动成功。查看日志中的具体错误。

### 3. 摄像头视频不刷新

检查：

```bash
python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8790/stream', timeout=5) as r:
    data = r.read(128)
print(b'--frame' in data and b'image/jpeg' in data)
PY
```

可能原因：

- OpenCV 不可用，JPEG 编码失败；
- 摄像头初始化失败；
- MediaPipe 初始化失败；
- Pi 负载过高导致视频编码变慢。

解决：

- 查看 `sudo journalctl -u pi-fusion -f`；
- 降低视频预览压力：

```yaml
preview:
  jpeg_quality: 60
  jpeg_every_n_frames: 3
```

### 4. 页面显示 PC `offline`

含义：树莓派端 `pi-fusion` 正在运行，但 PC 后端没有成功监听或连接。

检查 PC：

```powershell
netstat -ano | findstr ":9000"
Invoke-WebRequest http://127.0.0.1:5000/api/status
```

检查 Pi 日志：

```bash
sudo journalctl -u pi-fusion -f
```

常见日志：

```text
Reconnecting to 192.168.43.209:9000
```

说明 Pi 正在等待 PC 后端恢复。

### 5. micro:bit 原始数据刷新，但 `fused_frame.microbits[].available=false`

说明 micro:bit 数据到达 Pi，但与摄像头帧时间差超过阈值。

检查页面：

```text
microbits[].time_delta_ms
fusion_quality.missing_sources
```

调试阶段可临时放宽：

```yaml
fusion:
  max_age_ms: 300
```

正式采集时再逐步收紧同步阈值。

### 6. 预览造成树莓派负载偏高

当前预览不会重复运行 MediaPipe，也不会重复打开摄像头。主要额外负载来自 JPEG 编码和网页访问。

检查负载：

```bash
ps -o pid,stat,pcpu,pmem,etime,cmd -C python | grep fusion_pipeline
uptime
vcgencmd measure_temp
```

降低负载：

```yaml
preview:
  jpeg_quality: 55
  jpeg_every_n_frames: 4
```

如果要做严格训练采集，也可以关闭预览：

```yaml
preview:
  enabled: false
```

## 对后端数据接收的影响

本次更新不改变 PC 后端接收协议。

树莓派发送给 PC 后端的消息类型仍然是：

- `fused_frame`
- `control_event`
- `status`

发送方式仍然是：

```text
TCP JSON Lines -> PC backend :9000
```

主要变化是：`pi-fusion` 在调用 TCP 发送前，会把同一条消息复制一份到内存中的预览状态，供 `8790` 页面显示。

预览视频帧不会被发送给 PC 后端，`preview_jpeg` 也不会进入 `fused_frame.camera`。因此 PC 后端不会因为预览页面而收到更大的视频数据。

需要注意的变化：

1. `camera.hands[].world_landmarks` 已恢复，当 MediaPipe 检测到手时，PC 后端收到的 `fused_frame` 会包含该字段。
2. 如果启用视频预览，树莓派会有额外 JPEG 编码负载；在极端负载情况下，可能间接影响摄像头帧率和融合时间对齐。
3. 如果 PC 后端未运行，`8790` 页面仍可显示 Pi 端采集状态，但顶部 PC 状态会显示 `offline`。

## 快速验证命令

树莓派：

```bash
systemctl is-active pi-fusion
ss -ltunp | grep -E ':8790|:17778'
curl http://127.0.0.1:8790/state
```

PC：

```powershell
backend\.venv\Scripts\python.exe backend\app.py
Invoke-WebRequest http://127.0.0.1:5000/api/status
netstat -ano | findstr ":5000 :9000"
```

浏览器：

```text
http://192.168.43.221:8790/
```

