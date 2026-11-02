set root [file normalize [file dirname [file dirname [info script]]]]
set out [file join $root build uart_detector2]
set attempt [expr {[llength $argv] ? [lindex $argv 0] : "attempt1"}]
set dir [file join $out simulation $attempt]
if {[file exists $dir]} {error "Preserve previous simulation attempt"}
file mkdir $dir
create_project urx2_sim [file join $dir project] -part xc7z020clg400-1 -force
foreach name {uart_monitor_rx.sv urx2_rule_lane.sv urx2_detector.sv urx2_config_guard.sv urx2_axi.sv} {add_files [file join $root rtl $name]}
add_files -fileset sim_1 [file join $root tb tb_urx2_detector.sv]
set_property top tb_urx2_detector [get_filesets sim_1]
set_property target_simulator XSim [current_project]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sources_1
# Each case is independently launched with a bounded testbench watchdog.
foreach cfg [lsort [glob [file join $out vectors *_cfg.hex]]] {
    set name [string range [file tail $cfg] 0 end-8]
    if {[llength $argv]>1 && $name ne [lindex $argv 1]} {continue}
    set expected [file join $out vectors ${name}_expected.json]
    set fd [open $expected];set metadata [read $fd];close $fd
    regexp {"bytes": ([0-9]+)} $metadata -> count
    regexp {"end_ticks": ([0-9]+)} $metadata -> ending
    set options [list -testplusarg CFG=$cfg -testplusarg WIRE=[file join $out vectors ${name}_wire.hex] -testplusarg OUTPUT=[file join $dir ${name}.txt] -testplusarg COUNT=$count -testplusarg END=$ending]
    if {$name eq "parser_overload"} {lappend options -testplusarg GAP=1 -testplusarg OVERFLOW=1}
    set_property -dict [list xsim.simulate.xsim.more_options $options] [get_filesets sim_1]
    launch_simulation -mode behavioral
    if {$name eq "parallel8"} {
        open_vcd [file join $dir parallel8.vcd]
        log_vcd [get_objects {/tb_urx2_detector/clk /tb_urx2_detector/dut/frame_pulse /tb_urx2_detector/dut/lane_fire /tb_urx2_detector/dut/active_rules /tb_urx2_detector/event_valid /tb_urx2_detector/event_data}]
    }
    run 2sec
    if {$name eq "parallel8"} {close_vcd}
    close_sim
    set log [file join $dir project urx2_sim.sim sim_1 behav xsim simulate.log]
    file copy -force $log [file join $dir ${name}.log]
    set fd [open $log];set content [read $fd];close $fd
    if {![regexp {URX2_DETECTOR_CASE_PASS} $content] || [regexp {Fatal:|ERROR:} $content]} {error "URX2 case failed: $name"}
}
puts URX2_ALL_DETECTOR_SIMULATIONS_PASS
close_project
