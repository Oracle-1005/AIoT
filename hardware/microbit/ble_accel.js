/**
 * BLE Accelerometer Service — Direct BLE acceleration, no UART needed
 * Paste into MakeCode, add Bluetooth extension, enable "No Pairing Required"
 */
let DEVICE_ID = "A"

bluetooth.startAccelerometerService()
bluetooth.startButtonService()
bluetooth.setTransmitPower(7)

basic.showIcon(IconNames.Heart)
basic.pause(500)
basic.clearScreen()

// Also send device ID via UART
bluetooth.startUartService()

basic.forever(function () {
    // Send ID via UART every 500ms
    bluetooth.uartWriteString(DEVICE_ID + ","
        + input.acceleration(Dimension.X) + ","
        + input.acceleration(Dimension.Y) + ","
        + input.acceleration(Dimension.Z) + ","
        + input.runningTime() + "\n")
    basic.pause(100)
})
