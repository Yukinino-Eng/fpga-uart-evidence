# TUL PYNQ-Z2 user manual PDF p24/Table13 and vendored master XDC ja[0].
set_property -dict {PACKAGE_PIN Y18 IOSTANDARD LVCMOS33 PULLUP TRUE} [get_ports uart_rx]
# Asynchronous UART input ends at the first of two ASYNC_REG flip-flops.
set_false_path -from [get_ports uart_rx] -to [get_pins -hier -filter {NAME =~ *rx_meta_reg/D}]
