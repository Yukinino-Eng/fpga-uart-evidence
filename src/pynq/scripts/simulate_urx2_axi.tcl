set root [file normalize [file dirname [file dirname [info script]]]]
set attempt [expr {[llength $argv] ? [lindex $argv 0] : "attempt1"}]
set dir [file join $root build uart_detector2 axi_simulation $attempt]
if {[file exists $dir]} {error "Preserve previous AXI attempt"}
file mkdir $dir
create_project urx2_axi_sim [file join $dir project] -part xc7z020clg400-1 -force
foreach name {uart_monitor_rx.sv urx2_rule_lane.sv urx2_detector.sv urx2_config_guard.sv urx2_axi.sv} {add_files [file join $root rtl $name]}
add_files -fileset sim_1 [file join $root tb tb_urx2_axi.sv]
set_property top tb_urx2_axi [get_filesets sim_1]
set_property target_simulator XSim [current_project]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
set opts [list -testplusarg CFG=[file join $root build uart_detector2 vectors parallel8_cfg.hex] -testplusarg PACKET=[file join $root build uart_detector2 vectors axi_frame.hex]]
set_property -dict [list xsim.simulate.xsim.more_options $opts] [get_filesets sim_1]
update_compile_order -fileset sources_1
launch_simulation
run 2sec
close_sim
set log [file join $dir project urx2_axi_sim.sim sim_1 behav xsim simulate.log]
file copy -force $log [file join $dir simulation.log]
set fd [open $log];set content [read $fd];close $fd
if {![regexp {URX2_AXI_PASS} $content] || [regexp {Fatal:|ERROR:} $content]} {error "URX2 AXI simulation failed"}
puts URX2_AXI_SIMULATION_PASS
close_project
