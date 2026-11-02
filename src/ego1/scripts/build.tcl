# Clean project creation and implementation. No hardware or Flash access.
set root [file normalize [file dirname [file dirname [info script]]]]
set label [expr {[llength $argv]>0?[lindex $argv 0]:"release1"}]
set fps [expr {[llength $argv]>1?[lindex $argv 1]:10}]
set mode [expr {[llength $argv]>2?[lindex $argv 2]:-1}]
set duration [expr {[llength $argv]>3?[lindex $argv 3]:0}]
if {![regexp {^[A-Za-z0-9_]+$} $label]} {error "Invalid label"}
if {$fps ni {10 50} || $mode < -1 || $mode > 10 || $duration ni {0 20 60 180}} {error "Invalid build parameters"}
set dest [file join $root build $label]
if {[file exists $dest]} {error "Choose a new build label"}
create_project ego1_urx2_sender $dest -part xc7a35tcsg324-1
add_files [file join $root src ego1_urx2_source_top.sv]
add_files [list [file join $root reference rtl uart_tx.sv] [file join $root reference rtl button_debounce.sv]]
add_files -fileset constrs_1 [file join $root constraints ego1_urx2.xdc]
set_property top ego1_urx2_source_top [get_filesets sources_1]
set_property generic "FPS=$fps FIXED_CASE=$mode DURATION_SECONDS=$duration" [get_filesets sources_1]
set_property target_language Verilog [current_project]
set_property target_simulator XSim [current_project]
add_files -fileset sim_1 [file join $root tb tb_ego1_urx2.sv]
set_property top tb_ego1_urx2 [get_filesets sim_1]
update_compile_order -fileset sources_1
update_compile_order -fileset sim_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
launch_runs impl_1 -to_step route_design -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
open_run impl_1
set reports [file join $root verification $label]
file mkdir $reports
report_timing_summary -file [file join $reports timing_summary.rpt]
report_utilization -file [file join $reports utilization.rpt]
report_drc -file [file join $reports drc.rpt]
report_cdc -details -file [file join $reports cdc.rpt]
check_timing -verbose -file [file join $reports check_timing.rpt]
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {![llength $setup] || ![llength $hold]} {error "No timing paths"}
set wns [get_property SLACK $setup]
set whs [get_property SLACK $hold]
if {$wns < 0 || $whs < 0} {error "Timing failed WNS=$wns WHS=$whs"}
file mkdir [file join $root firmware]
write_bitstream [file join $root firmware "ego1_urx2_$label.bit"]
write_project_tcl -force -paths_relative_to $root [file join $reports recreate_project.tcl]
set f [open [file join $reports build_summary.txt] w]
puts $f "BUILD_PASS Vivado=[version -short] part=xc7a35tcsg324-1 fps=$fps mode=$mode duration=$duration WNS=$wns WHS=$whs"
close $f
puts "BUILD_PASS WNS=$wns WHS=$whs"
close_project
