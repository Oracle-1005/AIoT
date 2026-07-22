/**
 * BLE Debug Firmware — LED blink confirms code execution
 * =======================================================
 * LED behavior:
 *   - Heart on start (500ms)
 *   - Top-left pixel blinks every loop iteration
 *   - Center pixel blinks when uartWriteString is called
 * If top-left doesn't blink → forever loop not running
 * If top-left blinks but center doesn't → uartWriteString issue
 */
let DEVICE_ID = "A"
let ledState = 0

bluetooth.startUartService()
bluetooth.setTransmitPower(7)

basic.showIcon(IconNames.Heart)
basic.pause(500)
basic.clearScreen()

basic.forever(function () {
    // Toggle top-left LED to prove loop is running
    ledState = (ledState + 1) % 4
    if (ledState == 0) {
        led.plot(0, 0)
    } else if (ledState == 1) {
        led.unplot(0, 0)
    } else if (ledState == 2) {
        led.plot(0, 0)
    } else {
        led.unplot(0, 0)
    }

    // Build and send packet
    let packet = "" + DEVICE_ID + ","
        + input.acceleration(Dimension.X) + ","
        + input.acceleration(Dimension.Y) + ","
        + input.acceleration(Dimension.Z) + ","
        + input.runningTime() + "\n"

    // Flash center LED when sending
    led.plot(2, 2)
    bluetooth.uartWriteString(packet)
    led.unplot(2, 2)

    basic.pause(200)
})
