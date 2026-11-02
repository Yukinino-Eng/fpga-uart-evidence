set root [file normalize [file dirname [file dirname [info script]]]]
if {[llength $argv]!=1} {error "Expected accepted build label"}
set label [lindex $argv 0]
if {![regexp {^[A-Za-z0-9_]+$} $label]} {error "Invalid build label"}
set dest [file join $root build vivado 18_uart_detector2_$label]
open_project [file join $dest project uart_detector2.xpr]
open_run impl_1
set reports [file join $dest reports]
set lanes [get_cells -hier -filter {ORIG_REF_NAME =~ urx2_rule_lane*}]
if {[llength $lanes]!=8} {set lanes [get_cells -hier -filter {NAME =~ *detector/rules*.lane}]}
set out [open [file join $reports parallel_lanes.txt] w]
puts $out "RULE_LANE_COUNT=[llength $lanes]"
foreach lane $lanes {puts $out "LANE=$lane REF=[get_property REF_NAME $lane]"}
close $out
if {[llength $lanes]!=8} {error "Expected eight independently instantiated rule lanes"}
report_utilization -hierarchical -hierarchical_depth 8 -file [file join $reports hierarchy.rpt]
report_timing -max_paths 10 -input_pins -nets -file [file join $reports final_paths.rpt]
set out [open [file join $reports ram_modes.txt] w]
foreach cell [get_cells -hier -filter {REF_NAME =~ RAMB*}] {
    puts $out "RAM=$cell REF=[get_property REF_NAME $cell] A=[get_property WRITE_MODE_A $cell] B=[get_property WRITE_MODE_B $cell]"
}
close $out
puts URX2_EIGHT_PHYSICAL_RULE_LANES_VERIFIED
close_project
