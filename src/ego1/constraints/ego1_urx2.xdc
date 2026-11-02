# EGo1 v2.2 official manual sections 3, 5, 8 and 14.
# https://e-elements.readthedocs.io/zh/ego1_v2.2/EGo1.html
# Optional test-source overlay, never a PYNQ-Z2 constraint set.
set_property IOSTANDARD LVCMOS33 [get_ports *]
set_property PACKAGE_PIN P17 [get_ports sys_clk]
create_clock -name sys_clk -period 10.000 [get_ports sys_clk]
set_property PACKAGE_PIN P15 [get_ports fpga_reset]
set_property PULLUP true [get_ports fpga_reset]
set_property PACKAGE_PIN R11 [get_ports button_s0]
set_property PACKAGE_PIN R1 [get_ports {switches[0]}]
set_property PACKAGE_PIN N4 [get_ports {switches[1]}]
set_property PACKAGE_PIN M4 [get_ports {switches[2]}]
set_property PACKAGE_PIN R2 [get_ports {switches[3]}]
set_property PACKAGE_PIN P2 [get_ports {switches[4]}]
set_property PACKAGE_PIN T4 [get_ports uart_tx_o]
# J5 physical pin 15, IO_L4P, B11. J5 pins 33/34 are GND, 35/36 +3.3V.
set_property PACKAGE_PIN B11 [get_ports gpio_tx_o]
set_property PACKAGE_PIN K3 [get_ports {leds[0]}]
set_property PACKAGE_PIN M1 [get_ports {leds[1]}]
set_property PACKAGE_PIN L1 [get_ports {leds[2]}]
set_property PACKAGE_PIN K6 [get_ports {leds[3]}]
set_property PACKAGE_PIN J5 [get_ports {leds[4]}]
set_property PACKAGE_PIN H5 [get_ports {leds[5]}]
set_property PACKAGE_PIN H6 [get_ports {leds[6]}]
set_property PACKAGE_PIN K1 [get_ports {leds[7]}]
set_property DRIVE 4 [get_ports {uart_tx_o gpio_tx_o leds[*]}]
set_property SLEW SLOW [get_ports {uart_tx_o gpio_tx_o leds[*]}]
# Only asynchronous port-to-first-stage paths are excluded. Internal logic stays timed.
set_false_path -from [get_ports fpga_reset]
set_false_path -from [get_ports {switches[*]}] -to [get_pins -hier -filter {NAME =~ *sw_meta_reg*/D}]
set_false_path -from [get_ports button_s0] -to [get_pins -hier -filter {NAME =~ *button_meta_reg/D}]
# UART and LED outputs have no external synchronous reference clock.
set_false_path -to [get_ports {uart_tx_o gpio_tx_o leds[*]}]

set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
