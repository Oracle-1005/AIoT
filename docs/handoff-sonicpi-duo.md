# Sonic Pi duo 演奏系统 — 交接文档（2026-07-27)

> 面向组员：本文档汇总 duo 双曲演奏链路的**未决问题、已提交待验证的修复、验收步骤与演示日运维手册**。
> 最后提交 `cac794e`（master)。 deadline 2026-07-29。

---

## 0. 状态速览

| 项 | 状态 |
|---|---|
| 回卷线程死亡修复（拆共享 cue) | **已提交，运行时未验证** ← 最高优先 |
| GC 策略 | 暂定 GC.disable；节拍器方案待复测（可能无辜，见 §2) |
| duo 六阶段自动化验收 | **从未完整通过**（每次被上述死亡打断），步骤见 §3 |
| bass 音量 0.30→0.24 | 已提交，需耳听确认 |
| 前端 GestureConsole / 坐标识别器 / LED 双板波形 | 已上线已验收，与本文档问题无关 |
| 纪元围栏 / 启动驻停 / 命令去重 | 已提交（同批次），随验收一并验证 |

**给组员的一句话**：按 §1 验证回卷修复 → 按 §3 跑一遍六阶段验收 → 全绿则 Sonic Pi 侧收官；§4 是演示日必须照做的开机 checklist。

---

## 1. 【待验证】回卷线程死亡（本项目最隐蔽的 bug)

### 症状

Sonic Pi 运行 duo 构建后 **3 分 52 秒左右**(= Shape of You 93 小节 = 372 拍 = 232.5s @96BPM，即首次回卷点）,log 窗出现车轨线程死亡，**顺序固定为 13 → 12 → 8**:

```
Runtime Error: [buffer eval, line 84] - Thread death +--> :live_loop_soy_shape_track_13
Timing Exception: thread got too far behind time (SonicPi::Lang::Core::TimingError)
core.rb:4414:in 'SonicPi::Lang::Core#sleep'
```

- 四起死亡、三种 GC 配置、同一死法；死亡后**音乐听起来几乎正常**（少一条节奏轨难以察觉），状态上报照常（上报器是独立线程）。
- Windows v4.6 上**线程死亡不写任何磁盘日志**，只有 GUI log 窗可见——所以此前所有"浸泡验收"都没发现它。
- 历史教训：3 分钟浸泡(180s)< 一圈(232.5s),**从未测到过回卷**。浸泡时长必须超过曲目一圈。

### 根因（代码级分析，置信度高）

车轨 live_loop 顶部原有 `sync :soy_shape_cycle`（回卷对齐用）。回卷时 cycle clock 发 cue:

1. 共享 cue **同时唤醒全部 10 条车轨线程**（调度蜂群）;
2. Sonic Pi 的 `sync` 会让醒来的线程**采纳 cue 发送时刻的虚拟时间 vt**（一个过去值，`__change_spider_bpm_time_and_beat!`,core.rb:4540-4596);
3. 蜂群队尾的线程实际醒来时，已落后被采纳的 vt >1.75s;
4. 下一次 `sleep` 入口检查 `now > vt + sat + 1`(sat=0.75）即杀线程。

死亡顺序 13→12→8 就是蜂群调度的固定尾部——所以是**确定性**的，与 GC/机器负载无关（今天已排除 GC 嫌疑）。

### 修复（commit `cac794e`，已提交未验证）

**拆除共享 cue**：两个曲目源文件（`aiot_conductor_shape_of_you.rb` / `aiot_conductor_world_is_mine.rb`）中，车轨循环不再 `sync :*_cycle`,cycle clock 整个移除（源文件尾部有注释说明）。依据：Sonic Pi 的 sleep 是 deadline 制自纠偏（core.rb:4392-4430)，线程 vt 天然贴墙钟零漂移，回卷对齐本来就不需要 sync。

### 验证步骤（预计 15 分钟）

1. 完全退出 Sonic Pi（窗口 X),`tasklist` 确认无残留 erl/ruby/scsynth（有就杀）。
2. 重开，buffer 0(loader）按 **一次** Run。
3. **盯 log 窗 8 分钟**（= 扛过两次回卷）：零 Runtime Error = 修复成立。
4. 期间 `GET http://localhost:5000/api/music/state` 抽查：`last_bar` 应到 93 后回卷到小数，反馈新鲜度 <3s。
5. 通过 → 接 §3 六阶段验收。

---

## 2. 【待复测】GC 策略 — 节拍器方案可能是无辜的

| 方案 | 实测结果 |
|---|---|
| 裸跑（自动 GC) | 偶发大暂停 >1.75s 杀线程（理论风险，昨日曾发生） |
| `GC.disable` | 播放稳定，但堆涨 **~100MB/min**(25min→2.8GB 实测），长演示机器会卡 |
| 5Hz 节拍器每 10s `GC.start` | 今日 3 起死亡时它在场——**但事后证实四起死亡全部为 §1 回卷蜂群所致，与 GC 无关**;GC.start 的 >1.75s 全 VM 停顿目前只是理论风险 |

**当前提交**：暂回 `GC.disable` + 零强制 GC（谨慎起见），代价是内存增长 → 靠场次间重启消化（§4)。

**给组员的建议**：§1 修复验证通过后，把 wrapper 模板中 ticker 的 GC 节拍器加回来（`GC.start if (tick % 50) == 49`，被注释掉的版本在 git 历史里），重做 §1 的 8 分钟盯窗测试。若通过，则"不死线程 + 不涨内存"两全——这是演示日的最优配置。验证一次比争论一小时值钱。

---

## 3. duo 六阶段验收（手动步骤）

前置：后端运行中（Flask :5000),Sonic Pi 已按 §1 步骤 1-2 启动且 log 窗干净。
判据通用规则：每条命令发出前记 `t0`，之后查 `GET /api/music/state` 的 `last_sonic_pi_ack.received_at >= t0-1` 且 result 含对应关键字 = **新鲜 ack**;`last_beat_feedback_at` 与现在差 <3s = 反馈新鲜；两次采样 `last_bar` 不同 = 小节推进。

| # | 操作 | 通过判据 |
|---|---|---|
| ① | `POST /api/sonic-pi/transport {"action":"next"}` | ≤12s 内 title 变 World is Mine,bpm=132，新鲜 transport ack，小节推进；5s 后不串回 soy |
| ② | `POST /api/music/layers {"layer":"drums","enabled":false}` 然后 `POST /api/music/style {"style":"next"}` | 各自新鲜 layer/style ack;layers.drums=false;style 从 piano_pop 变 vocaloid_electro |
| ③ | `POST /api/sonic-pi/transport {"action":"prev"}` | title 回 Shape of You,bpm=96,**style 仍是 festival_edm、drums=true**(soy 未被污染） |
| ④ | 再 `{"action":"next"}` | wim **记忆保持**:drums 仍 false、style 仍 vocaloid_electro，其他声部 true |
| ⑤ | 还原：drums=true、style `previous`（回 piano_pop)、prev 回 soy | 终态 = soy 播放 + wim 默认还原 |
| ⑥ | 浸泡 **≥5 分钟**（须 >232.5s!) | 每 10s 采样：无幻影切歌、反馈新鲜 <5s、last_bar 不停滞；回卷发生属正常 |

全绿后：**人工**点前端 prev/next 按钮各一次（耳听真切歌），并确认 bass 音量（0.24 不合适再调）。

PowerShell 调接口注意：curl 的 JSON 双引号会被吃，用 Git Bash curl 或 `Invoke-RestMethod`。

---

## 4. 演示日运维 playbook(Sonic Pi v4.6 / Windows，全部实测实锤）

**开机 checklist（顺序执行）**:

1. `netstat -ano -p udp | grep 4560` —— 必须显示某 **erl.exe** 的 PID。Tau 可能半启动：进程活着但不占 4560，症状是**反馈活、命令死**（切歌/调层全无响应、无 ack)。修复 = 完全退出重开。
2. `tasklist | grep -iE "erl|ruby|scsynth|sonic"` —— 单实例 5 进程（sonic-pi×1、erl×1、ruby×2、scsynth×1)。多出来的 = 孤儿，杀掉（GUI 关闭后孤儿 ruby/scsynth 会继续"无声演奏")。
3. buffer 0 的 loader 按 **一次** Run。**同会话绝不按第二次 Run**——每次 Run 产生一个 run 家族，Stop/再 Run 不杀旧家族的 run_file 子 run（纪元围栏只是保险）。改任何 rb 后：完全退出重开再 Run。
4. 发一条 `transport:stop` 再 `start`，两条都有新鲜 ack → 才允许开场。

**场次间**：每 ~20-30 分钟完全退出重开一次（消化 GC.disable 的内存增长 + 清 Tau)。

**其他红线**:
- buffer 只贴 `aiot_loader.rb`（主脚本 run_file 磁盘读）;Run 按钮 OSC 包有 16384 字节硬上限，超限静默截断。
- rb 源文件**纯 ASCII**（构建脚本按 ascii 读，一个中文注释就炸构建）。
- loader 内路径 `D:/CC/AIoT/...` 换机器要改。

---

## 5. 其他风险与悬置问题

- **热点稳定性是演出最大单点风险**（3 次闪断史）：热点手机插电 + 关自动关热点 + 锁 2.4GHz；不行换路由器组网。
- 机位/镜像勿动（handedness 无镜像配置，一动左右全反）；演示双 micro:bit 必戴。
- 悬置待拍板："一曲结束自动切下一曲？" 建议**保持手动**（切歌 = 演示交互卖点；单曲本就无限循环）。如要可加 auto-advance 开关（默认关）。
- sklearn 1.9 训练 / 1.8 加载的警告无害。

## 6. 关键文件

| 文件 | 说明 |
|---|---|
| `music/sonic_pi/aiot_loader.rb` | 唯一进 buffer 的文件（879B) |
| `music/sonic_pi/build_duo_wrapper.py` | duo 构建脚本（含 7a/7b 驻停门禁、命名空间注入） |
| `music/sonic_pi/build/aiot_conductor_duo.rb` 等 ×3 | 构建产物，ruby -c 已过 |
| `music/sonic_pi/aiot_conductor_{shape_of_you,world_is_mine}.rb` | 曲目源（尾部注释记录回卷修复缘由） |
| 后端 `/api/sonic-pi/transport`、`/api/music/{layers,style,state}` | 验收接口 |
