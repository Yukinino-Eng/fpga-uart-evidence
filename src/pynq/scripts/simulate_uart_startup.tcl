set root [file normalize [file dirname [file dirname [info script]]]]
set label [expr {[llength $argv] ? [lindex $argv 0] : "updated_01"}]
set old [expr {[llength $argv]>1 && [lindex $argv 1] eq "baseline"}]
set out [file join $root build uart_startup_20261101 simulation $label]
if {[file exists $out]} {error "Preserve previous startup simulation"}
file mkdir $out
create_project uart_startup [file join $out project] -part xc7z020clg400-1 -force
foreach name {uart_monitor_rx.sv urx2_rule_lane.sv urx2_detector.sv urx2_config_guard.sv} {
    add_files [file join $root rtl $name]
}
if {$old} {add_files [file join $root build uart_startup_20261101 before urx2_axi.sv]} else {add_files [file join $root rtl urx2_axi.sv]}
add_files -fileset sim_1 [file join $root tb tb_urx2_startup.sv]
set_property top tb_urx2_startup [get_filesets sim_1]
set_property target_simulator XSim [current_project]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
if {$old} {set_property -dict [list xsim.simulate.xsim.more_options {-testplusarg BASELINE}] [get_filesets sim_1]}
update_compile_order -fileset sources_1
puts "STARTUP_PREFLIGHT part=[get_property part [current_project]] simulator=[get_property target_simulator [current_project]] top=[get_property top [get_filesets sim_1]]"
launch_simulation -mode behavioral
open_vcd [file join $out startup.vcd]
log_vcd [get_objects {/tb_urx2_startup/rst /tb_urx2_startup/rx /tb_urx2_startup/dut/enabled /tb_urx2_startup/dut/clear_pulse /tb_urx2_startup/dut/u_rx/state /tb_urx2_startup/dut/u_rx/rx_clean /tb_urx2_startup/dut/uart_valid /tb_urx2_startup/dut/uart_error /tb_urx2_startup/dut/framing_errors}]
run 150ms
close_vcd
close_sim
set log [file join $out project uart_startup.sim sim_1 behav xsim simulate.log]
file copy -force $log [file join $out simulation.log]
set fd [open $log];set content [read $fd];close $fd
if {$old} {
    if {![regexp {UART_STARTUP_BASELINE_REPRODUCED} $content]} {error "Baseline did not reproduce the claimed design failure"}
    puts UART_STARTUP_BASELINE_REPRODUCED
} else {
    if {![regexp {UART_STARTUP_SYNC_PASS} $content] || [regexp {UART_STARTUP_FAIL|Fatal:|ERROR:} $content]} {error "Startup regression failed"}
    puts UART_STARTUP_REGRESSION_PASS
}
close_project
