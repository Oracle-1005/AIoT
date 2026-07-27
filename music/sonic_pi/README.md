# Sonic Pi 五曲目播放工作流

本目录只保留由 Sonic Pi 内置合成器和采样直接发音的实现，不再依赖
loopMIDI、REAPER 或外部 VST。正式运行入口只有 `aiot_loader.rb`。

## 曲目与风格

| 顺序 | 曲目 ID | 默认 BPM | 风格 |
|---|---|---:|---|
| 1 | `shape_of_you` | 96 | `acoustic_pop`、`tropical_house`、`festival_edm` |
| 2 | `world_is_mine` | 132 | `piano_pop`、`vocaloid_electro`、`rock_band` |
| 3 | `faded` | 90 | `piano_ballad`、`synthwave`、`festival` |
| 4 | `lemon` | 87 | `acoustic_ballad`、`modern_pop`、`cinematic_rock`、`lofi_night` |
| 5 | `rolling_girl` | 98 | `piano_drama`、`electro_punk`、`vocaloid_rock`、`lofi_breakbeat` |

每首曲目均支持 `melody`、`harmony`、`bass`、`drums` 四个逻辑声部。切歌时，
各曲目的 BPM、音量、风格和声部开关分别保存；`reset` 恢复当前曲目的默认状态。

## 正式启动

1. 完全退出并重新打开 Sonic Pi，避免旧 live loop 继续运行。
2. 在 Sonic Pi 中打开 `music/sonic_pi/aiot_loader.rb`，只点击一次 `Run`。
3. 启动 PC 后端。
4. 查看 `GET /api/sonic-pi/status`，确认：
   - `command_channel_ready=true`
   - `audio_output_mode=internal`
   - `pending_commands=0`

loader 只负责从磁盘加载较大的构建文件，不要把 `build/*.rb` 粘贴进 Sonic Pi
缓冲区，也不要在同一会话中重复运行 loader。

## 构建文件

编辑曲目源文件或构建器后执行：

```powershell
backend\.venv\Scripts\python.exe music\sonic_pi\build_playlist_wrapper.py
```

构建结果：

| 文件 | 用途 |
|---|---|
| `build/aiot_track_soy.rb` | Shape of You 命名空间曲目 |
| `build/aiot_track_wim.rb` | World is Mine 命名空间曲目 |
| `build/aiot_track_faded.rb` | Faded 命名空间曲目 |
| `build/aiot_track_lemon.rb` | Lemon 命名空间曲目 |
| `build/aiot_track_rolling.rb` | Rolling Girl 命名空间曲目 |
| `build/aiot_conductor_playlist.rb` | 五曲目切换、控制、ACK、去重和状态反馈 |
| `aiot_loader.rb` | Sonic Pi 唯一正式入口 |

不要直接修改 `build/`，它会在下一次构建时被覆盖。

## 控制方式

PC 后端继续使用既有接口：

```text
POST /api/sonic-pi/transport  {"action":"next","wait_ms":1500}
POST /api/music/style         {"style":"next","wait_ms":1500}
POST /api/music/layers        {"layer":"drums","enabled":false,"wait_ms":1500}
POST /api/sonic-pi/state      {"bpm":108,"master_amp":0.5,"wait_ms":1500}
```

`transport` 支持 `start`、`pause`、`stop`、`cutoff`、`reset`、`next` 和
`previous`。完整 OSC 约定见
[`../../docs/SONIC_PI_OSC_CONTRACT.md`](../../docs/SONIC_PI_OSC_CONTRACT.md)。

## 十分钟轮测

后端和 Sonic Pi 启动后运行：

```powershell
backend\.venv\Scripts\python.exe backend\verify_sonic_pi_playlist.py
```

默认验证一个五曲目周期，共约 10 分钟：

- 每 120 秒切换到下一首曲目。
- 每首曲目的第 25、50、75、100 秒切换到下一个风格。
- 四个时点依次关闭 melody、harmony、bass、drums，并在下一时点恢复上一声部。
- 每条 REST/OSC 命令必须收到 ACK，节拍反馈必须持续，超时计数不得增长。
- 运行记录写入 `music/sonic_pi/validation_logs/*.jsonl`，该目录不提交 Git。

先查看计划而不连接后端：

```powershell
backend\.venv\Scripts\python.exe backend\verify_sonic_pi_playlist.py --dry-run
```

脚本可以发现命令失联、ACK 超时和节拍反馈中断，但 Sonic Pi 4.6 的个别线程
`TimingError` 不一定传回后端。因此轮测期间仍需观察 Sonic Pi GUI，结束时确认没有
`Runtime Error`、`Serious timing error` 或 `can't keep up`。

如果脚本提示后端 API 过旧，或 `/api/music/layers` 返回 404，说明 `5000` 端口仍有
旧后端进程。停止全部 `5000` 监听进程，再使用项目的 `backend\.venv` 启动后端。

## 单曲调试

`run_shape_of_you.rb`、`run_world_is_mine.rb`、`run_faded.rb`、`run_lemon.rb` 和
`run_rolling_girl.rb` 仅用于脱离播放列表调试单曲。单曲入口和 `aiot_loader.rb`
不能在同一个 Sonic Pi 会话中同时运行。
