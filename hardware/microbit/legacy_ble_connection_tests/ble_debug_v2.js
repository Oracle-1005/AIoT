/**
 * BLE Debug v2 — Connection detection + LED feedback
 * ==================================================
 * LED meanings:
 *   Heart (startup) → Yes (BLE connected) / No (disconnected)
 *   Top-left: slow blink = loop running
 *   Center: ON = uartWriteString called (stays ON if blocks!)
 */
let DEVICE_ID = "A"
let step = 0

bluetooth.startUartService()
bluetooth.setTransmitPower(7)

bluetooth.onBluetoothConnected(function () {
    basic.showIcon(IconNames.Yes)
    basic.pause(1000)
    basic.clearScreen()
})

bluetooth.onBluetoothDisconnected(function () {
    basic.showIcon(IconNames.No)
    basic.pause(1000)
    basic.clearScreen()
})

basic.showIcon(IconNames.Heart)
basic.pause(800)
basic.clearScreen()

basic.forever(function () {
    // Top-left blink
    step = (step + 1) % 6
    if (step < 3) {
        led.plot(0, 0)
    } else {
        led.unplot(0, 0)
    }

    // Center ON
    led.plot(2, 2)
    basic.pause(100)

    // Send
    let packet = "" + DEVICE_ID + ","
        + input.acceleration(Dimension.X) + ","
        + input.acceleration(Dimension.Y) + ","
        + input.acceleration(Dimension.Z) + ","
        + input.runningTime() + "\n"
    bluetooth.uartWriteString(packet)

    // Center OFF
    led.unplot(2, 2)
    basic.pause(100)
})
