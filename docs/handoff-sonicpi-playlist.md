# Sonic Pi 五曲目系统交接文档

本文记录当前五曲目工作流、现场启动、可靠性约束和验收方法。音频完全由 Sonic Pi
内置合成器与采样输出，不需要外部 DAW 或 VST。

## 当前能力

| 项目 | 状态 |
|---|---|
| 五曲目统一运行 | Shape of You、World is Mine、Faded、Lemon、Rolling Girl |
| 曲目切换 | `next`、`previous`，各曲目独立保存状态 |
| 风格切换 | 每首 3 至 4 个预设，支持 `next`、`previous` 和明确预设名 |
| 声部开关 | melody、harmony、bass、drums |
| 命令可靠性 | command ID、ACK、有限重试、重复命令幂等缓存 |
| 通道健康检查 | `/conductor/ping` 与 `/music/pong` |
| 输出模式 | 固定 `internal`，Sonic Pi 直接完整发声 |
| 回卷调度 | 已移除共享 cycle cue，避免回卷时集中唤醒线程 |

## 现场启动

1. 完全退出 Sonic Pi 后重新打开。
2. 打开 `music/sonic_pi/aiot_loader.rb`，只运行一次。
3. 在项目根目录启动后端：

```powershell
backend\.venv\Scripts\python.exe backend\app.py
```

4. 确认控制通道和输出：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/sonic-pi/status
Invoke-RestMethod http://127.0.0.1:5000/api/music/state
```

通过条件：

- `command_channel_ready` 为 `true`
- `audio_output_mode` 为 `internal`
- `pending_commands` 为 `0`
- `last_beat_feedback_at` 持续刷新

若 Sonic Pi 已打开但状态不满足条件，应完整退出再重开，不要再次点击同一 loader 的
Run。旧 live loop 可能仍在运行并造成双重播放、抢占反馈或命令重复。

## 控制验收

```powershell
$next = @{ action = "next"; wait_ms = 1500 } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/sonic-pi/transport `
  -ContentType application/json -Body $next

$style = @{ style = "next"; wait_ms = 1500 } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/music/style `
  -ContentType application/json -Body $style

$layer = @{ layer = "drums"; enabled = $false; wait_ms = 1500 } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/music/layers `
  -ContentType application/json -Body $layer
```

每条响应的 `delivery.status` 应为 `acked`，之后
`GET /api/music/state` 的曲目、风格和声部状态应与命令一致。

## 长时间轮测

```powershell
backend\.venv\Scripts\python.exe backend\verify_sonic_pi_playlist.py
```

默认过程约 10 分钟。每首曲目运行 120 秒，并在 25 秒间隔切换风格、轮流开关四个
声部，再切到下一首。脚本在任一 ACK、心跳、节拍或状态检查失败时以非零状态退出，
并把最后状态写入 `music/sonic_pi/validation_logs/*.jsonl`。

轮测期间保持 Sonic Pi GUI 可见。脚本通过只表示 REST/OSC 和节拍反馈正常；最终还
必须人工确认 GUI 中没有 `Runtime Error`、`Serious timing error` 或
`can't keep up`。

## 可靠性语义

1. 后端为命令生成唯一 `command_id`。
2. 未收到 ACK 时有限重发；`accent` 除外，避免补播过时重音。
3. Sonic Pi 播放列表统一缓存最近 64 个命令结果。相同 ID 的 UDP 重发只重复 ACK，
   不重复执行切歌、风格或声部副作用。
4. 连续 BPM、音量、state 和同一声部命令采用最新值优先。
5. 五首曲目在同一进程内运行，只有当前曲目推进和发声，切歌使用 epoch 围栏阻止
   旧曲目的尾部事件泄漏。

## 常见问题

| 现象 | 处理 |
|---|---|
| 只有部分声部有声音 | 查看 `/api/music/state` 的 `layers`，必要时依次恢复为 `true` |
| 命令无 ACK | 检查 `command_channel_ready`、UDP 4560/4561 和 Sonic Pi 单实例 |
| `/api/music/layers` 返回 404 | 旧后端仍占用 `5000`；停止所有监听进程，再用项目虚拟环境启动 |
| `timed_out_commands` 增长 | 查看 Sonic Pi GUI CPU/错误，完整重启 Sonic Pi |
| 切歌两次或两首同时响 | 已重复运行 loader；完整退出 Sonic Pi 后只运行一次 |
| 修改 RB 后没有生效 | 运行构建器，随后完整重启 Sonic Pi |
| 长时间出现 timing error | 保存轮测 JSONL，记录出错曲目、风格、声部和时间点 |

## 关键文件

| 文件 | 用途 |
|---|---|
| `music/sonic_pi/aiot_loader.rb` | 唯一正式 Sonic Pi 入口 |
| `music/sonic_pi/build_playlist_wrapper.py` | 生成五曲目命名空间、wrapper 和 loader |
| `music/sonic_pi/build/aiot_conductor_playlist.rb` | 统一控制、切歌、ACK 和反馈 |
| `music/sonic_pi/build/aiot_track_*.rb` | 五首命名空间曲目 |
| `backend/sonic_pi.py` | OSC 发送、重试、ACK 和健康状态 |
| `backend/app.py` | REST 控制接口 |
| `backend/verify_sonic_pi_playlist.py` | 120 秒切歌、25 秒轮测脚本 |
| `docs/SONIC_PI_OSC_CONTRACT.md` | 完整接口约定 |

当前仍保留 `GC.disable` 以减小实时播放抖动，因此连续演示之间建议重启 Sonic Pi。
