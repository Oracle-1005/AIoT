# Sonic Pi 问题解决方案与应用方法

本文档说明 AIoT 智能指挥项目当前的 Sonic Pi 播放方案、问题修复、启动步骤、控制
接口和验证方法。当前正式方案由 Sonic Pi 内置合成器与采样直接发声，不依赖外部
DAW、虚拟 MIDI 端口或 VST。

## 1. 当前架构

```text
树莓派传感器
    |
    v
PC 后端 REST/动作识别
    |
    | OSC/UDP 127.0.0.1:4560
    v
Sonic Pi 五曲目播放列表
    |
    | OSC/UDP 127.0.0.1:4561
    v
PC 后端 ACK、心跳、曲目、节拍、风格和声部状态
```

五首曲目按以下顺序循环：

```text
Shape of You
-> World is Mine
-> Faded
-> Lemon
-> Rolling Girl
-> Shape of You
```

每首曲目支持：

- `start`、`pause`、`stop`、`reset`、`next`、`previous`
- BPM 调整
- 总音量调整
- 3 至 4 个曲目专属风格
- `melody`、`harmony`、`bass`、`drums` 四个声部开关
- 当前曲目的腕部重音事件

## 2. 已解决的问题

### 2.1 只听到鼓组

旧方案可把旋律、和声和低音发送到外部音源。如果外部音轨未正确监听，Sonic Pi
本身只能听到鼓组。

当前方案已移除外部音源分支，所有声部都由 Sonic Pi 直接播放。后端状态中的
`audio_output_mode` 必须为 `internal`。

### 2.2 曲目回卷后出现 timing error

旧曲目在循环边界使用共享 cycle cue，同时唤醒多个线程，容易触发：

```text
Serious timing error. Too far behind time
Timing error: can't keep up
```

当前曲目已移除共享 cycle 同步点，各轨道按自身虚拟时间循环，降低循环边界的集中
调度压力。

### 2.3 实时指令偶发丢失或重复

控制命令现在带有唯一 `command_id`：

1. 后端在 ACK 超时前有限重发。
2. Sonic Pi 缓存最近 64 个命令结果。
3. 重复 ID 只返回原 ACK，不重复执行切歌、风格或声部副作用。
4. BPM、音量、state 和同一声部命令采用最新值优先。
5. `accent` 不重发，避免延迟后补播已经过时的重音。

### 2.4 多个后端同时占用 5000

典型表现：

- 验证脚本提示 `command channel is not ready`。
- `POST /api/music/layers` 返回 HTTP 404。
- `/api/sonic-pi/status` 中没有 `command_channel_ready`、
  `audio_output_mode`、`pending_commands` 等字段。
- `/api/music/state` 仍显示旧曲目，例如 `Ode to Joy`。

这说明请求命中了旧后端，而不是五曲目后端。禁止使用裸命令：

```powershell
python backend\app.py
```

该命令可能调用 Anaconda 或系统 Python。必须使用项目虚拟环境。

## 3. 清理旧后端

在 PowerShell 中查看所有 `5000` 监听进程：

```powershell
netstat -ano | findstr :5000
```

只记录状态为 `LISTENING` 的 PID，然后查看进程：

```powershell
Get-Process -Id <PID>
```

确认这些 PID 是旧的 Python 后端后停止：

```powershell
Stop-Process -Id <PID1>,<PID2> -Force
```

再次检查，必须没有 `LISTENING`：

```powershell
netstat -ano | findstr :5000
```

不要停止与 `5000` 无关的 Python、Sonic Pi、模型训练或其他开发进程。

## 4. 正确启动顺序

### 4.1 重建 Sonic Pi 文件

修改曲目源或构建器后，在项目根目录执行：

```powershell
backend\.venv\Scripts\python.exe music\sonic_pi\build_playlist_wrapper.py
```

不要直接修改 `music/sonic_pi/build/` 中的生成文件。

### 4.2 启动 Sonic Pi

1. 完全退出 Sonic Pi，而不只是点击 Stop。
2. 重新打开 Sonic Pi。
3. 打开 `music/sonic_pi/aiot_loader.rb`。
4. 只点击一次 Run。

不要同时运行 `run_*.rb` 单曲入口和 `aiot_loader.rb`，也不要在同一 Sonic Pi 会话
重复运行 loader。

### 4.3 启动 PC 后端

在新的 PowerShell 中执行：

```powershell
cd G:\code\AIoT\AIoT
backend\.venv\Scripts\python.exe backend\app.py
```

保持该终端运行。正常情况下只应有一组后端监听 `5000`。

## 5. 启动状态检查

```powershell
$sp = Invoke-RestMethod http://127.0.0.1:5000/api/sonic-pi/status
$music = Invoke-RestMethod http://127.0.0.1:5000/api/music/state
$sp
$music
```

最低通过条件：

| 字段 | 预期 |
|---|---|
| `command_channel_ready` | `true` |
| `audio_output_mode` | `internal` |
| `pending_commands` | 很快回到 `0` |
| `timed_out_commands` | 不持续增长 |
| `track_count` | `5` |
| `track_id` | 五首曲目 ID 之一 |
| `layers` | 包含四个声部 |
| `last_beat_feedback_at` | 持续刷新 |

如果状态缺少上述字段，应先处理旧后端占用问题，不要反复运行 Sonic Pi loader。

## 6. 手动控制验证

### 6.1 开始播放

```powershell
$body = @{ action = "start"; wait_ms = 1500 } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/sonic-pi/transport `
  -ContentType application/json -Body $body
```

### 6.2 切换曲目

```powershell
$body = @{ action = "next"; wait_ms = 1500 } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/sonic-pi/transport `
  -ContentType application/json -Body $body
```

### 6.3 切换风格

```powershell
$body = @{ style = "next"; wait_ms = 1500 } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/music/style `
  -ContentType application/json -Body $body
```

### 6.4 开关声部

```powershell
$off = @{ layer = "drums"; enabled = $false; wait_ms = 1500 } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/music/layers `
  -ContentType application/json -Body $off

$on = @{ layer = "drums"; enabled = $true; wait_ms = 1500 } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/music/layers `
  -ContentType application/json -Body $on
```

每条响应必须满足：

```text
sent = true
delivery.status = acked
```

## 7. 五曲目长时间验证

确认 Sonic Pi 和新版后端都已启动后运行：

```powershell
backend\.venv\Scripts\python.exe backend\verify_sonic_pi_playlist.py
```

默认过程约 10 分钟：

1. 每首曲目运行 120 秒。
2. 在第 25、50、75、100 秒切换到下一个风格。
3. 依次关闭 melody、harmony、bass、drums。
4. 每次关闭下一个声部前恢复上一个声部。
5. 第 120 秒恢复全部声部并切换曲目。
6. 每条命令检查 ACK、通道心跳、节拍反馈和超时计数。

日志保存到：

```text
music/sonic_pi/validation_logs/playlist_YYYYMMDD_HHMMSS.jsonl
```

只查看计划、不连接后端：

```powershell
backend\.venv\Scripts\python.exe backend\verify_sonic_pi_playlist.py --dry-run
```

验证脚本通过不代表 Sonic Pi GUI 一定没有单线程错误。测试期间应保持 GUI 可见，并
确认没有：

```text
Runtime Error
Serious timing error
Timing error: can't keep up
```

## 8. 文件位置

| 文件 | 用途 |
|---|---|
| `music/sonic_pi/aiot_loader.rb` | 正式 Sonic Pi 启动入口 |
| `music/sonic_pi/build_playlist_wrapper.py` | 五曲目构建器 |
| `music/sonic_pi/build/aiot_conductor_playlist.rb` | 统一控制和切歌 wrapper |
| `music/sonic_pi/build/aiot_track_*.rb` | 五首命名空间曲目 |
| `backend/sonic_pi.py` | OSC、ACK、重试和心跳 |
| `backend/verify_sonic_pi_playlist.py` | 十分钟轮测脚本 |
| `docs/SONIC_PI_OSC_CONTRACT.md` | 完整 OSC/REST 接口 |
| `docs/handoff-sonicpi-playlist.md` | 现场交接与故障速查 |

## 9. 使用约束

- 修改 RB 后必须重新构建，并完整重启 Sonic Pi。
- 正式运行只执行 `aiot_loader.rb` 一次。
- 后端必须使用 `backend\.venv`，不得使用 Anaconda 的裸 `python`。
- 长时间演示前必须运行轮测。
- 当前使用 `GC.disable` 减小实时调度抖动，连续演示之间建议重启 Sonic Pi。
