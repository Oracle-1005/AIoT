摇晃是否会产生冲突？	**取消摇晃事件**

如何判断长按？ 	**micro:bit内部完成判断**

普通状态发送被控制事件延迟时如何同步？ 以采样时间戳为准；事件首次发送优先，重复包与状态包交错发送。

**控制事件的优先级(priority)延后完成**

# 双micro:bit --> 树莓派

| 内容           | 说明                                                 |
| -------------- | ---------------------------------------------------- |
| 连接方式       | BLE                                                  |
| micro:bit 程序 | MakeCode                                             |
| 树莓派接收库   | Python `Bleak`                                       |
| 采集内容       | `acc_x`、`acc_y`、`acc_z`、Pitch、Roll、按键控制事件 |
| 输出格式       | 不超过 20 B 的定长二进制数据包                       |
| 采样率         | 25～50 Hz                                            |

## 数据包设计

双 micro:bit 向树莓派发送两种独立的数据结构：

1. **持续状态包 `sensor_state`**
   - 以固定采样率 25~50 Hz 周期发送；
   - 携带三轴加速度、Pitch、Roll,不包含按键状态和其他状态位；
   - 用于姿态分析、动作特征提取和后续多模态融合。

2. **控制事件包 `control_event`**
   - 由 micro:bit 内部完成按键按下、长按和组合键判断；
   - 事件确认后立即发送；
   - 同一事件重复**发送多次以防止丢包**，树莓派负责去重；
   - 保留 `priority` 字段；
   - 用于开始、暂停、风格切换、紧急停止和校准等安全或系统级控制。

| 消息            | 用途                 | 发送方式           | 长度 |
| --------------- | -------------------- | ------------------ | ---: |
| `sensor_state`  | 连续加速度与姿态数据 | 25～50 Hz 周期发送 | 17 B |
| `control_event` | 已确认的控制事件     | 事件发生后重复发送 | 11 B |

两种数据包满足规则：

- 第 1 字节为组合 `header`,`header` 同时包含 `message_type` 和 `hand`；树莓派通过 `header` 解析消息类型和左右手身份。
- 不包含 `version`,`checksum` 或 CRC；
- 使用 Little Endian(小端序)；
- 单包长度不超过 BLE UART 的 20 B 有效载荷；
- 保留设备时间戳和序号,供丢包检测及后续时间同步使用。
- 由树莓派在接收时记录 `pi_rx_monotonic_ns`。
- 时间戳必须在采样时记录，树莓派按采样时间排序，不按到达顺序排序。
- 控制事件只能延迟 `sensor_state` 的 BLE 发送，不能延迟 IMU 的固定周期采样。
- 延迟状态包不应直接用于时钟偏移更新。

------

### 1字节组合头 header

|  Bit | 字段           |  长度 | 说明         |
| ---: | -------------- | ----: | ------------ |
| 0～1 | `message_type` | 2 bit | 数据包类型   |
|    2 | `hand`         | 1 bit | 左右手标识   |
| 3～7 | `reserved`     | 5 bit | 当前必须为 0 |

#### `message_type` 定义

| 二进制 | 十进制 | 名称            |
| ------ | -----: | --------------- |
| `00`   |      0 | 保留            |
| `01`   |      1 | `sensor_state`  |
| `10`   |      2 | `control_event` |
| `11`   |      3 | 保留            |

#### `hand` 定义

|   值 | 含义         |
| ---: | ------------ |
|  `0` | 左手 `left`  |
|  `1` | 右手 `right` |

#### Header 取值示例

| Header | 二进制      | 消息类型        | 手别 |
| -----: | ----------- | --------------- | ---- |
| `0x01` | `0000 0001` | `sensor_state`  | 左手 |
| `0x05` | `0000 0101` | `sensor_state`  | 右手 |
| `0x02` | `0000 0010` | `control_event` | 左手 |
| `0x06` | `0000 0110` | `control_event` | 右手 |

### 持续状态包 `sensor_state`

`sensor_state` 只表示某个采样时刻的手腕运动状态。

包含：

- 三轴加速度；
- Pitch；
- Roll；
- 采样序号；
- micro:bit 启动后的毫秒时间。

#### 数据结构

```
uint8   header
uint16  sample_sequence
uint32  device_timestamp_ms
int16   ax_mg
int16   ay_mg
int16   az_mg
int16   pitch_deg
int16   roll_deg
```

总长度：

```text
1 + 2 + 4 + 2 + 2 + 2 + 2 + 2 = 17 B
```

#### 字节布局

| 偏移 | 字段                  | 大小 | 类型        | 说明                                               |
| ---: | --------------------- | ---: | ----------- | -------------------------------------------------- |
|    0 | `header`              |  1 B | `uint8`     | 消息类型与左右手                                   |
|    1 | `sample_sequence`     |  2 B | `uint16 LE` | 每产生一个新传感器样本时递增，即使该样本最终未发送 |
|    3 | `device_timestamp_ms` |  4 B | `uint32 LE` | micro:bit 启动后的毫秒时间                         |
|    7 | `ax_mg`               |  2 B | `int16 LE`  | X 轴加速度，单位 mg                                |
|    9 | `ay_mg`               |  2 B | `int16 LE`  | Y 轴加速度，单位 mg                                |
|   11 | `az_mg`               |  2 B | `int16 LE`  | Z 轴加速度，单位 mg                                |
|   13 | `pitch_deg`           |  2 B | `int16 LE`  | Pitch，单位 degree                                 |
|   15 | `roll_deg`            |  2 B | `int16 LE`  | Roll，单位 degree                                  |

#### 采样参数

| 参数             |    推荐值 |
| ---------------- | --------: |
| 初始采样率       |     25 Hz |
| 采样周期         |     40 ms |
| 可测试采样率     |     50 Hz |
| 加速度量程       |      ±4 g |
| 强动作频繁饱和时 | 改为 ±8 g |



### 控制事件包 `control_event`

`control_event` 用于传输由 micro:bit 内部已经确认的一次性事件，例如：

- A 按下；
- B 按下；
- B 长按；
- A+B 长按；

事件发生时立即发送，不等待下一个 `sensor_state` 采样周期。树莓派直接根据 `event_code` 判断事件类型。

#### 数据结构

```
uint8   header
uint16  event_sequence
uint32  device_timestamp_ms
uint8   event_code
uint8   priority
uint8   repeat_index
uint8   repeat_total
```

总长度：

```text
1 + 2 + 4 + 1 + 1 + 1 + 1 = 11 B
```

#### 字节布局

| 偏移 | 字段                  | 大小 | 类型        | 说明             |
| ---- | --------------------- | ---- | ----------- | ---------------- |
| 0    | `header`              | 1 B  | `uint8`     | 消息类型与左右手 |
| 1    | `event_sequence`      | 2 B  | `uint16 LE` | 每个新事件递增   |
| 3    | `device_timestamp_ms` | 4 B  | `uint32 LE` | 事件确认时刻     |
| 7    | `event_code`          | 1 B  | `uint8`     | 事件类型         |
| 8    | `priority`            | 1 B  | `uint8`     | 建议优先级       |
| 9    | `repeat_index`        | 1 B  | `uint8`     | 当前重复编号     |
| 10   | `repeat_total`        | 1 B  | `uint8`     | 总发送次数       |

#### 事件码

| 值           | 事件            |
| ------------ | --------------- |
| `0x01`       | `A_SHORT_PRESS` |
| `0x02`       | `B_SHORT_PRESS` |
| `0x03`       | `B_LONG_PRESS`  |
| `0x04`       | `AB_LONG_PRESS` |
| `0x05～0xFF` | 保留            |

```
按键按下
  ↓
开始计时
  ↓
持续按住
  ├─ 达到长按阈值 → 立即产生一次 LONG_PRESS
  │                    设置 long_reported=true
  │
  └─ 未达到阈值

按键释放
  ├─ long_reported=false 且不是组合键
  │      → 产生一次 SHORT_PRESS
  │
  └─ long_reported=true
         → 不再产生任何按键事件
         
         
检测到 A、B 同时按下后：
1. 进入 AB 组合状态；
2. 取消 B_LONG_PRESS 的独立计时；
3. 禁止产生 A_SHORT_PRESS；
4. 禁止产生 B_SHORT_PRESS；
5. 达到阈值时只产生 AB_LONG_PRESS；
6. 两个按钮全部释放后才退出组合状态。
```

#### 优先级(候选)

| priority | 等级 | 示例           |
| -------: | ---- | -------------- |
|      100 | 紧急 | 右手 B 长按    |
|       60 | 中高 | 暂停、重新校准 |
|       40 | 中   | 开始、继续     |
|       20 | 普通 | 风格切换       |

| 手别与事件             | 系统语义   | priority |
| ---------------------- | ---------- | -------: |
| 左手 `A_SHORT_PRESS`   | 开始或继续 |       40 |
| 左手 `B_SHORT_PRESS`   | 暂停       |       60 |
| 右手 `A_SHORT_PRESS`   | 风格切换   |       20 |
| 右手 `B_LONG_PRESS`    | 紧急停止   |      100 |
| 任一手 `AB_LONG_PRESS` | 重新校准   |       60 |

```python
await control_queue.put(
    (-event.priority, arrival_counter, event)
)
```

### 控制事件重复发送

每个新事件：

1. 分配新的 `event_sequence`；
2. 保存事件确认时的 `device_timestamp_ms`；
3. 创建不可变事件记录；
4. 默认重复发送 3 次；
5. 每次只修改 `repeat_index`。

| 参数             |    推荐值 |
| ---------------- | --------: |
| `repeat_total`   |         3 |
| 相邻重复发送间隔 |     20 ms |
| 总发送跨度       |  约 40 ms |
| 事件队列最大长度 |         8 |
| 普通按键防抖     | 50～80 ms |

树莓派只执行第一次收到的有效事件，其余重复包只用于提高成功送达概率。

------

### micro:bit 发送优先级调度

micro:bit 维护两种发送任务：

```text
高优先级：control_event
普通优先级：sensor_state
```

调度方法：

```text
检查是否有到期的控制事件重复包
1. 新控制事件的第一次发送，最高优先级；
2. 已到期的最新 sensor_state；
3. 控制事件的第二、第三次重复发送；
4. 重复包与状态包交错发送；
5. 只有新的紧急事件可以立即抢占状态包；
6. 不等待全部重复包发送完成后再恢复状态发送。
```

------

### BLE Notify 接收与分流

```text
左腕 micro:bit（BLE Peripheral） ─┐
                                  ├─ BLE UART Notify ─→ 树莓派（BLE Central）
右腕 micro:bit（BLE Peripheral） ─┘
```

| 项目           | 方案                             |
| -------------- | -------------------------------- |
| micro:bit 角色 | BLE Peripheral                   |
| 树莓派角色     | BLE Central                      |
| micro:bit 开发 | MakeCode TypeScript              |
| 树莓派接收     | Python + Bleak + BlueZ           |
| BLE Service    | micro:bit Bluetooth UART Service |
| 上行方式       | BLE Indication                   |
| Bleak 接收 API | client.start_notify()            |
| 数值字节序     | Little Endian                    |
| 最大包长       | 不超过 20 B                      |
| 左右手区分     | `hand` 字段与设备地址共同确认    |

BLE UART TX Characteristic：

```text
6E400002-B5A3-F393-E0A9-E50E24DCCA9E
```

树莓派订阅同一个 TX Characteristic，即可接收两种消息。每次通知到达后读取首字节 `header`，再使用对应结构解析。

#### 分流过程

```
BLE Notify 到达
  ↓
立即记录 pi_rx_monotonic_ns
  ↓
检查 payload 非空
  ↓
读取 header
  ↓
解析 message_type 和 hand
  ↓
检查来源设备与 hand 是否一致
  ├─ sensor_state → sensor_queue
  └─ control_event → control_queue
```

### 控制事件去重

树莓派使用：

```text
(hand, event_sequence)
```

作为主要去重键。

去重缓存 TTL：

```text
5～10 秒
```

处理规则：

```text
首次收到：
    接受并执行
    写入 seen_events

后续重复收到：
    只增加重复包统计
    不再次执行

同一去重键但内容不一致：
    记录协议异常
    丢弃
    
发生 BLE 断线重连时：
    清除该设备的控制事件去重缓存

检测到 device_timestamp_ms 明显回退时：
    判断设备重启
    清除该手的 seen_events
    重置 sample_sequence 跟踪
```

------

### 树莓派优先处理方式

使用两个独立通道：

```
sensor_queue
control_queue
```

其中：

- `sensor_queue` 用于普通持续状态；
- `control_queue` 用于控制事件；
- 控制事件消费者独立运行，不等待状态数据处理；
- 紧急停止不经过滤波、摄像头融合或时间同步等待。

#### 队列容量

| 队列            | 推荐容量 | 队列满处理                   |
| --------------- | -------: | ---------------------------- |
| `sensor_queue`  | 128～256 | 丢弃最旧状态包               |
| `control_queue` |     无界 | 事件频率低，记录队列长度异常 |

```
control_queue = asyncio.PriorityQueue() 暂时使用无界优先队列
```

#### 控制事件处理流程

```text
control_queue
  ↓
解析 control_event
  ↓
去重检查
  ↓
优先级检查
  ↓
映射系统候选事件
  ↓
紧急事件立即上报
普通事件进入 PC 仲裁
```

#### 紧急事件快速路径

```text
右手 B_LONG_PRESS
  ↓
control_event，priority=100
  ↓
重复发送 3 次
  ↓
树莓派首次收到
  ↓
按 (hand, event_sequence) 登记
  ↓
立即生成 emergency_stop
  ↓
直接上报 PC
```

### 持续状态序号处理

每只手独立维护：

```text
last_sample_sequence
```

期望序号：

```text
expected = (last_sample_sequence + 1) mod 65536
```

| 情况                       | 处理                                                         |
| -------------------------- | ------------------------------------------------------------ |
| 当前序号等于期望值         | 正常                                                         |
| 当前序号等于上一序号       | 重复包，丢弃                                                 |
| 当前序号向前跳跃           | 记录 missing_sample_count 或 sequence_gap。 该值表示缺失样本数，不直接等同于 BLE 丢包数。 |
| 序号大幅回退且时间戳也变小 | 判断设备重启                                                 |
| BLE 重连                   | 重置或重新初始化序号跟踪                                     |

### 可靠性检查

```
- payload 不能为空；
- sensor_state 长度必须为 17 B；
- control_event 长度必须为 11 B；
- header 保留位必须为 0；
- message_type 必须为 1 或 2；
- hand 必须与 BLE 设备来源一致；
- event_code 必须已定义且适用于对应手别；
- priority 必须与 hand + event_code 映射一致；
- repeat_total > 0；
- repeat_index < repeat_total；
- 同一 event_sequence 的重复包除 repeat_index 外必须完全一致；
- device_timestamp_ms 应基本单调递增；
- ax、ay、az、Pitch、Roll 必须位于协议允许范围。
```

## 与时间同步模块的接口

```python
import struct

SENSOR_STATE_STRUCT = struct.Struct("<BHIhhhhh")
CONTROL_EVENT_STRUCT = struct.Struct("<BHIBBBB")

assert SENSOR_STATE_STRUCT.size == 17
assert CONTROL_EVENT_STRUCT.size == 11
```

### `sensor_state` 输出示例

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

### `control_event` 输出示例

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

