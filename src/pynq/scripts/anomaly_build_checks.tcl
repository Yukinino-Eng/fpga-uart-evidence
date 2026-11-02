# Gate the timing-summary coverage before publishing a performance bitstream.
# Asynchronous board I/O is reported separately; internal endpoints must be timed.
proc check_anomaly_timing_coverage {timing_file} {
    set stream [open $timing_file r]
    set timing [read $stream]
    close $stream
    foreach category {no_clock unconstrained_internal_endpoints} {
        set pattern [format {checking %s \(([0-9]+)\)} $category]
        if {![regexp $pattern $timing ignored count] || $count != 0} {
            error "Missing or failing timing coverage category: $category"
        }
    }
}
