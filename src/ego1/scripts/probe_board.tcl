# Read-only JTAG inventory. Never programs a device.
open_hw_manager
connect_hw_server -url localhost:3121
set targets [get_hw_targets]
foreach target $targets {
    current_hw_target $target
    open_hw_target
    puts "TARGET_ID=$target"
    foreach dev [get_hw_devices] {puts "DEVICE_ID=$dev PART=[get_property PART $dev]"}
    close_hw_target
}
close_hw_manager
