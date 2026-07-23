/**
 * Micro:bit V2 — BLE UART Accelerometer Firmware
 * ===============================================
 * MakeCode JavaScript + Bluetooth Extension
 *
 * 功能: 通过 BLE UART 以 ~50Hz 发送加速度数据
 * 数据格式: "A,acc_x,acc_y,acc_z,running_time_ms\n"
 *
 * 刷写步骤见 README_BLE.md
 *
 * DEVICE_ID: 左手="A", 右手="B"（两个设备各自修改第25行）
 */

// ============================================================
// 配置 — 刷第二个设备时改这里为 "B"
// ============================================================
let DEVICE_ID = "A"

// ============================================================
// 初始化
// ============================================================
bluetooth.startUartService()
bluetooth.setTransmitPower(7)

basic.showIcon(IconNames.Heart)
basic.pause(500)
basic.clearScreen()

let connected = false
let lastSample = 0

// BLE 连接状态回调
bluetooth.onBluetoothConnected(function () {
    connected = true
    basic.showIcon(IconNames.Yes)
    basic.pause(500)
    basic.clearScreen()
})

bluetooth.onBluetoothDisconnected(function () {
    connected = false
    basic.showIcon(IconNames.No)
    basic.pause(500)
    basic.clearScreen()
})

// ============================================================
// 主循环 — 50Hz 加速度采集 + BLE UART 发送
// ============================================================
basic.forever(function () {
    let now = input.runningTime()

    // 限速 50Hz (20ms interval)
    if (now - lastSample >= 20) {
        lastSample = now

        let accX = input.acceleration(Dimension.X)  // mg
        let accY = input.acceleration(Dimension.Y)
        let accZ = input.acceleration(Dimension.Z)

        // 组装数据包: "DEVICE_ID,accX,accY,accZ,timestamp_ms\n"
        let packet = "" + DEVICE_ID + "," + accX + "," + accY + "," + accZ + "," + now + "\n"

        // BLE UART 发送
        if (connected) {
            bluetooth.uartWriteString(packet)
        }
    }

    // LED 心跳指示
    if (connected) {
        led.plot(2, 2)  // 中心点 = 已连接
    } else {
        led.unplot(2, 2)  // 灭 = 等待连接
    }

    basic.pause(1)
})
