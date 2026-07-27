# Sonic Pi OSC 接口与可靠传输约定

本文描述 PC 后端与 Sonic Pi 五曲目播放列表之间的实时控制接口。该接口不改变
树莓派、Micro:bit、模型、数据库或 LED 协议。

## 运行拓扑

```text
树莓派传感数据 -> PC 后端 -> OSC/UDP 127.0.0.1:4560 -> Sonic Pi
                              <- OSC/UDP 127.0.0.1:4561 <-
```

| 方向 | 地址 | 用途 |
|---|---|---|
| 后端 -> Sonic Pi | `127.0.0.1:4560` | 播放、切歌、BPM、音量、风格和声部命令 |
| Sonic Pi -> 后端 | `127.0.0.1:4561` | ACK、心跳、节拍和实际播放状态 |

`/music/beat` 有反馈只能证明播放线程仍在运行。只有 `/music/pong` 和对应命令的
`/music/ack` 能证明命令接收通道正常。

## 可靠性语义

- 后端为每条命令生成唯一 `command_id`。
- 除 `/conductor/accent` 外，未收到 ACK 的命令会有限重发。
- Sonic Pi 播放列表缓存最近 64 个命令结果；重复 ID 返回原 ACK，不重复执行副作用。
- `state`、`bpm`、`volume` 和同一声部的 `layer` 采用最新值优先。
- `transport` 和 `style` 不合并，依靠 command ID 保证幂等和顺序。
- `accent` 不重发，避免延迟补播已经过时的重音。
- 同一 command ID 不得用于不同路径或参数，否则返回冲突结果。

默认后端参数：

```dotenv
AIOT_SONIC_PI_ACK_TIMEOUT=1.5
AIOT_SONIC_PI_PING_INTERVAL=2.0
```

## 后端发往 Sonic Pi

```text
/conductor/transport command_id action
/conductor/state command_id bpm master_amp drum_amp drum_density bass_amp harmony_amp melody_amp energy reverb_mix cutoff [style]
/conductor/bpm command_id bpm
/conductor/volume command_id volume
/conductor/style command_id style
/conductor/layer command_id layer enabled
/conductor/accent command_id strength type
/conductor/ping command_id
```

| 命令 | 支持值 |
|---|---|
| `transport action` | `start`、`resume`、`play`、`pause`、`stop`、`cutoff`、`reset`、`next`、`previous` |
| `bpm` | `72..148` |
| `volume/master_amp` | `0.0..1.0`，曲目内部平滑趋近 |
| `style` | `next`、`previous` 或当前曲目的明确预设名 |
| `layer` | `melody`、`harmony`、`bass`、`drums` |
| `enabled` | `1.0` 开启，`0.0` 关闭 |

`/conductor/state` 的通用风格值 `piano`、`strings`、`brass` 会按当前曲目映射到
前三个实际预设。明确预设名只在对应曲目中生效；非法风格返回 `invalid_style`。

## Sonic Pi 返回后端

| OSC 路径 | 参数 | 用途 |
|---|---|---|
| `/music/ack` | `command_id, result` | 命令已执行，或重复命令的原结果 |
| `/music/pong` | `command_id, epoch` | 命令通道健康检查 |
| `/music/output` | `internal` | Sonic Pi 内置音源完整输出 |
| `/music/track` | `piece_id, title, key, total_bars, beats_per_bar, default_bpm` | 当前曲目 |
| `/music/beat` | `bar, beat, bpm, beat_strength` | 节拍反馈 |
| `/music/bar` | `bar, section` | 小节反馈 |
| `/music/state` | `playing, bpm, section, energy` | 实际播放状态 |
| `/music/layers` | `melody, harmony, bass, drums` | 实际声部开关 |
| `/music/style` | `track_id, style` | 实际风格 |

曲目顺序固定为：

```text
shape_of_you -> world_is_mine -> faded -> lemon -> rolling_girl -> shape_of_you
```

前端应以 `/music/track`、`/music/state`、`/music/layers` 和 `/music/style` 的反馈
作为最终显示值，不应只显示发送命令前的意图值。

## REST 验证

发送命令时可附带 `wait_ms`，最大等待 2000 ms：

```powershell
$body = @{ action = "start"; wait_ms = 1500 } | ConvertTo-Json
$result = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/sonic-pi/transport `
  -ContentType application/json -Body $body
$result
```

用响应中的 ID 查询后续结果：

```powershell
Invoke-RestMethod `
  http://127.0.0.1:5000/api/sonic-pi/commands/<command_id>
```

健康状态：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/sonic-pi/status
Invoke-RestMethod http://127.0.0.1:5000/api/music/state
```

| 字段 | 判定 |
|---|---|
| `command_channel_ready` | 最近收到 pong，命令入口可用 |
| `pending_commands` | 等待 ACK 的命令数，应很快回到 0 |
| `last_ack_latency_ms` | 最近命令确认延迟 |
| `retried_messages` | UDP 丢失或 Sonic Pi 忙时发生过重试 |
| `timed_out_commands` | 重试后仍未确认；持续增长表示链路异常 |
| `last_ping_latency_ms` | 最近命令通道往返延迟 |
| `audio_output_mode` | 当前实现必须为 `internal` |

## 当前运行文件

```text
music/sonic_pi/aiot_loader.rb
music/sonic_pi/build/aiot_conductor_playlist.rb
music/sonic_pi/build/aiot_track_soy.rb
music/sonic_pi/build/aiot_track_wim.rb
music/sonic_pi/build/aiot_track_faded.rb
music/sonic_pi/build/aiot_track_lemon.rb
music/sonic_pi/build/aiot_track_rolling.rb
```

修改源曲目或构建脚本后执行：

```powershell
backend\.venv\Scripts\python.exe music\sonic_pi\build_playlist_wrapper.py
```

然后完整退出并重新打开 Sonic Pi，再运行 `aiot_loader.rb` 一次。
