/**
 * Minimal BLE UART Test — 10Hz accelerometer
 * Paste into MakeCode JavaScript editor
 * Remember: add Bluetooth extension + enable "No Pairing Required"
 */
let DEVICE_ID = "A"

basic.showIcon(IconNames.Heart)
basic.pause(1000)

bluetooth.startUartService()
bluetooth.setTransmitPower(7)
basic.clearScreen()

let connected = false

bluetooth.onBluetoothConnected(function () {
    connected = true
    basic.showIcon(IconNames.Yes)
})

bluetooth.onBluetoothDisconnected(function () {
    connected = false
    basic.showIcon(IconNames.No)
})

basic.forever(function () {
    if (connected) {
        let packet = "" + DEVICE_ID + ","
            + input.acceleration(Dimension.X) + ","
            + input.acceleration(Dimension.Y) + ","
            + input.acceleration(Dimension.Z) + ","
            + input.runningTime() + "\n"
        bluetooth.uartWriteString(packet)
    }
    basic.pause(100)
})
