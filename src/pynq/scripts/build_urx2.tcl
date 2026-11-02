# Independent URX2; original URX2, CAR1 and SBB4/SBB5 outputs remain unchanged.
set root [file normalize [file dirname [file dirname [info script]]]]
set attempt [expr {[llength $argv] ? [lindex $argv 0] : "final"}]
if {![regexp {^[A-Za-z0-9_]+$} $attempt]} {error "Invalid build label"}
set dest [file join $root build vivado 18_uart_detector2_$attempt]
if {[file exists $dest]} {error "Preserve existing build; choose a new attempt label"}
set reports [file join $dest reports]
file mkdir $reports
set_param board.repoPaths [list [file join $root assets pynq-z2 board_files]]
create_project uart_detector2 [file join $dest project] -part xc7z020clg400-1 -force
set board [get_board_parts -quiet tul.com.tw:pynq-z2:part0:*]
if {[llength $board]!=1} {error "Expected one vendored PYNQ-Z2 board definition"}
set_property board_part $board [current_project]
add_files [list [file join $root rtl uart_monitor_rx.sv] [file join $root rtl urx2_rule_lane.sv] [file join $root rtl urx2_detector.sv] [file join $root rtl urx2_config_guard.sv] [file join $root rtl urx2_axi.sv] [file join $root rtl urx2_bd.v]]
add_files -fileset constrs_1 [file join $root constraints uart_monitor_pynq_z2.xdc]
create_bd_design system
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:* ps7
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable"} [get_bd_cells ps7]
proc urx_configure_checked {cell config} {
    set_property -dict $config [get_bd_cells $cell]
    foreach {key value} $config {
        set actual [get_property $key [get_bd_cells $cell]]
        if {[string is double -strict $value] && [string is double -strict $actual]} {
            if {$actual!=$value} {error "$cell $key did not take effect"}
        } elseif {$actual ne $value} {error "$cell $key did not take effect: $actual"}
    }
}
urx_configure_checked ps7 {CONFIG.PCW_USE_M_AXI_GP0 1 CONFIG.PCW_USE_S_AXI_HP0 0 CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ 100 CONFIG.PCW_EN_CLK0_PORT 1}
create_bd_cell -type module -reference urx2_bd uart_rx_0
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:* control
urx_configure_checked control {CONFIG.NUM_SI 1 CONFIG.NUM_MI 1}
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:* reset
urx_configure_checked reset {CONFIG.C_AUX_RESET_HIGH 0}
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:* one
urx_configure_checked one {CONFIG.CONST_WIDTH 1 CONFIG.CONST_VAL 1}
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:* zero
urx_configure_checked zero {CONFIG.CONST_WIDTH 1 CONFIG.CONST_VAL 0}
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins control/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins control/M00_AXI] [get_bd_intf_pins uart_rx_0/S_AXI]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins ps7/M_AXI_GP0_ACLK] [get_bd_pins reset/slowest_sync_clk] [get_bd_pins uart_rx_0/aclk]
foreach pin [get_bd_pins -of_objects [get_bd_cells control] -filter {TYPE == clk && DIR == I}] {connect_bd_net [get_bd_pins ps7/FCLK_CLK0] $pin}
foreach pin [get_bd_pins -of_objects [get_bd_cells control] -filter {TYPE == rst && DIR == I}] {connect_bd_net [get_bd_pins reset/interconnect_aresetn] $pin}
connect_bd_net [get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins reset/ext_reset_in]
connect_bd_net [get_bd_pins one/dout] [get_bd_pins reset/dcm_locked] [get_bd_pins reset/aux_reset_in]
connect_bd_net [get_bd_pins zero/dout] [get_bd_pins reset/mb_debug_sys_rst]
connect_bd_net [get_bd_pins reset/peripheral_aresetn] [get_bd_pins uart_rx_0/aresetn]
create_bd_port -dir I uart_rx
connect_bd_net [get_bd_ports uart_rx] [get_bd_pins uart_rx_0/uart_rx]
assign_bd_address
set_property offset 0x43C10000 [get_bd_addr_segs ps7/Data/SEG_uart_rx_0_reg0]
set_property range 64K [get_bd_addr_segs ps7/Data/SEG_uart_rx_0_reg0]
validate_bd_design
if {[get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells reset]]!=0 || [get_property CONFIG.C_AUX_RESET_HIGH [get_bd_cells reset]]!=0} {error "Unexpected active-low reset polarity"}
save_bd_design
write_bd_tcl -force [file join $reports system.tcl]
set cfg [open [file join $reports configuration.txt] w]
puts $cfg "VIVADO=[version -short]\nPART=[get_property PART [current_project]]\nBOARD=[get_property BOARD_PART [current_project]]\nUART_PIN=Y18\nUART_BAUDS=9600,19200,38400,57600,115200\nFCLK_MHZ=100\nFIFO_BYTES=4096"
close $cfg
foreach cell {ps7 control reset} {report_property [get_bd_cells $cell] -file [file join $reports ${cell}_properties.txt]}
set bd [get_files */system.bd]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {error "URX2 synthesis failed"}
set_property strategy Performance_ExplorePostRoutePhysOpt [get_runs impl_1]
if {[get_property strategy [get_runs impl_1]] ne "Performance_ExplorePostRoutePhysOpt"} {error "Implementation strategy readback mismatch"}
launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {error "URX2 implementation failed"}
open_run impl_1
report_timing_summary -report_unconstrained -file [file join $reports timing.rpt]
report_utilization -file [file join $reports utilization.rpt]
report_drc -file [file join $reports drc.rpt]
report_cdc -details -file [file join $reports cdc.rpt]
report_methodology -file [file join $reports methodology.rpt]
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
if {$wns<0 || $whs<0} {error "URX2 timing failure"}
if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]} {error "URX2 DRC errors"}
if {![llength [get_cells -hier -filter {REF_NAME =~ RAMB*}]]} {error "Expected BRAM FIFO inference"}
if {[llength [get_pins -hier -filter {NAME =~ *rx_meta_reg/D}]]!=1} {error "UART CDC first stage not uniquely identified"}
source [file join $root scripts anomaly_build_checks.tcl]
check_anomaly_timing_coverage [file join $reports timing.rpt]
set deliver [file join $root build pynq_z2 uart_detector2 $attempt firmware]
file mkdir $deliver
file copy -force [file join $dest project uart_detector2.runs impl_1 system_wrapper.bit] [file join $deliver uart_detector2.bit]
file copy -force [file join $dest project uart_detector2.gen sources_1 bd system hw_handoff system.hwh] [file join $deliver uart_detector2.hwh]
write_hw_platform -fixed -include_bit -force -file [file join $deliver uart_detector2.xsa]
set out [open [file join $reports build_pass.txt] w]
puts $out "PART=xc7z020clg400-1\nWNS=$wns\nWHS=$whs\nDRC_ERRORS=0\nNO_CLOCK=0\nUNCONSTRAINED_INTERNAL_ENDPOINTS=0\nHARDWARE_VALIDATED=NO\nUART_PIN=Y18\nUART_DIRECTION=INPUT_ONLY"
close $out
puts URX2_BUILD_PASS
close_project
