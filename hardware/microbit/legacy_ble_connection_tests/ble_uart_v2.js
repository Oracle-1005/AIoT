/**
 * BLE UART Accelerometer v2 — Always send, no connection check
 * Paste into MakeCode, add Bluetooth extension, enable "No Pairing Required"
 */
let DEVICE_ID = "A"

bluetooth.startUartService()
bluetooth.setTransmitPower(7)

basic.showIcon(IconNames.Heart)
basic.pause(500)
basic.clearScreen()

basic.forever(function () {
    let packet = "" + DEVICE_ID + ","
        + input.acceleration(Dimension.X) + ","
        + input.acceleration(Dimension.Y) + ","
        + input.acceleration(Dimension.Z) + ","
        + input.runningTime() + "\n"
    bluetooth.uartWriteString(packet)
    basic.pause(20)
})
