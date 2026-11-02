# Volatile configuration only; require exactly one Artix-7 target.
set root [file normalize [file dirname [file dirname [info script]]]]
set image [file join $root firmware ego1_urx2_release2.bit]
if {![file isfile $image]} {error "Missing verified bitstream"}
open_hw_manager
connect_hw_server -url localhost:3121
set targets [get_hw_targets]
if {[llength $targets]!=1} {error "Expected exactly one JTAG target; refusing ambiguous hardware"}
current_hw_target [lindex $targets 0]
open_hw_target
set devices [get_hw_devices]
if {[llength $devices]!=1} {error "Expected exactly one FPGA"}
set dev [lindex $devices 0]
if {[get_property PART $dev] ne "xc7a35t"} {error "Expected EGo1 xc7a35t, not PYNQ or another device"}
puts "PROGRAM_TARGET=$dev PART=[get_property PART $dev] IMAGE=$image"
set_property PROGRAM.FILE $image $dev
program_hw_devices $dev
refresh_hw_device $dev
report_property $dev
puts "VOLATILE_PROGRAM_PASS"
close_hw_target
close_hw_manager
