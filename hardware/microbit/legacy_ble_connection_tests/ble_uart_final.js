/**
 * BLE UART Accelerometer — Final Version
 * ======================================
 * DEVICE_ID: "A" = left, "B" = right (change for second micro:bit)
 *
 * Steps in MakeCode:
 * 1. Paste this code (JavaScript mode)
 * 2. Add Bluetooth extension
 * 3. Enable "No Pairing Required" in Project Settings
 * 4. Flash via WebUSB (click arrow next to Download)
 */
let DEVICE_ID = "A"

bluetooth.startUartService()
bluetooth.setTransmitPower(7)

basic.showIcon(IconNames.Heart)
basic.pause(500)
basic.clearScreen()

let lastSample = 0

basic.forever(function () {
    let now = input.runningTime()
    if (now - lastSample >= 15) {
        lastSample = now
        bluetooth.uartWriteString(
            "" + DEVICE_ID + ","
            + input.acceleration(Dimension.X) + ","
            + input.acceleration(Dimension.Y) + ","
            + input.acceleration(Dimension.Z) + ","
            + now + "\n"
        )
    }
    basic.pause(5)
})
