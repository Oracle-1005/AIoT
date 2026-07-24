# micro:bit Radio 转 USB 网关

该工程仅用于通过 USB 连接树莓派的第三块 micro:bit。网关监听 MakeCode Radio
组 `79`，将收到的无线载荷原样转发到 USB 串口，不解析左右手传感器数据。

## 当前串口接口

- 波特率：`115200`
- 启动消息：`GW1,READY,79`
- 数据消息：`GW1,<gateway_rx_ms>,<rssi_dbm>,<radio_serial>,<payload_hex>`
- 状态消息：按网关板 A 键输出
  `GW1,STATUS,<gateway_uptime_ms>,<received_count>,79`

LED 矩阵显示 `G` 表示网关固件已启动；右下角像素在每次收到 Radio
数据时切换亮灭。

## 当前发送端

左右手 micro:bit 均运行 `hardware/microbit/microbit_to_pi/` 中的
MakeCode Radio 固件，并使用 Radio 组 `79`：

- 左手发送周期：`47 ms`
- 右手发送周期：`53 ms`
- 每个传感样本发送 `2` 次，间隔 `15 ms`
- 传感包：`17 B`
- 控制事件包：`11 B`，同一事件重复发送 `7` 次

左右手采用不同的互质发送周期，避免两块独立启动的设备长期同相碰撞。
树莓派由 `fusion_pipeline/radio_serial_adapter.py` 读取本串口。
