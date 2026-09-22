# Check the board-part recovery in scripts/build_zedboard.tcl without Vivado.
#
#   tclsh scripts/test_board_part_match.tcl
#
# That path only runs on a machine where the configured board part is NOT
# installed, so it never runs here and never ran in any build that worked. It
# then failed on the user's machine at its very first line: regsub read a
# pattern beginning with a dash as a switch. This pins that down.
#
# Only wm_same_device is exercised. The rest of build_zedboard.tcl needs Vivado.

set here [file normalize [file dirname [info script]]]
set src  [file join $here build_zedboard.tcl]

# Take the proc out of the build script rather than copying it, so this tests
# the file that runs rather than a second copy of it that can drift.
set fh [open $src r] ; set txt [read $fh] ; close $fh
foreach name {wm_same_device wm_pick_board} {
    if {![regexp -- "(?s)(proc $name \\{.*?\\n\\})" $txt -> body]} {
        puts "FAIL: $name not found in $src"
        exit 1
    }
    eval $body
}

# name -> PART_NAME, as get_board_parts / get_property report them.
set installed {
    xilinx.com:zc702:part0:1.4        xc7z020clg484-1
    xilinx.com:zc706:part0:1.4        xc7z045ffg900-2
    em.avnet.com:zed:part0:1.4        xc7z020clg484-1
    xilinx.com:kc705:part0:1.6        xc7k325tffg900-2
    digilentinc.com:arty-a7-35:part0:1.1  xc7a35ticsg324-1L
}

set failures 0
proc case {name part installed want} {
    set got [wm_same_device $part $installed]
    if {$got eq $want} {
        puts [format "  ok    %-34s -> %s" $name [expr {$got eq {} ? {(none)} : $got}]]
    } else {
        puts [format "  FAIL  %-34s" $name]
        puts "        want: $want"
        puts "        got : $got"
        incr ::failures
    }
}

# The real case: the ZedBoard part is configured, both it and ZC702 are on
# xc7z020clg484, and either one's PS preset will do.
case "xc7z020clg484-1, both installed" xc7z020clg484-1 $installed \
     {em.avnet.com:zed:part0:1.4 xilinx.com:zc702:part0:1.4}

# A speed grade the device does not have installed still matches the device.
case "xc7z020clg484-3, speed grade differs" xc7z020clg484-3 $installed \
     {em.avnet.com:zed:part0:1.4 xilinx.com:zc702:part0:1.4}

# A device nothing is installed for: the empty list is what makes the script
# print its "install a board part" message instead of building without a PS.
case "xc7z010clg400-1, nothing matches" xc7z010clg400-1 $installed {}

# No dash to strip: the pattern must not eat anything, and must not error.
case "no speed grade suffix" xc7z020clg484 $installed \
     {em.avnet.com:zed:part0:1.4 xilinx.com:zc702:part0:1.4}

# Nothing installed at all.
case "empty board part list" xc7z020clg484-1 {} {}

# A different family must not match on a shared prefix.
case "xc7k325tffg900-2" xc7k325tffg900-2 $installed {xilinx.com:kc705:part0:1.6}

proc pick {name board matches want} {
    set got [wm_pick_board $board $matches]
    if {$got eq $want} {
        puts [format "  ok    %-34s -> %s" $name [expr {$got eq {} ? {(none)} : $got}]]
    } else {
        puts [format "  FAIL  %-34s" $name]
        puts "        want: $want"
        puts "        got : $got"
        incr ::failures
    }
}

puts ""
set zed em.avnet.com:zed:part0:1.4

# The one that matters: the ZedBoard part is installed, just not at the version
# asked for. Its own PS preset must win over another board on the same device.
pick "prefer the same board, other version" $zed \
     {em.avnet.com:zed:part0:1.3 xilinx.com:zc702:part0:1.4} \
     em.avnet.com:zed:part0:1.3
pick "highest version of the same board" $zed \
     {em.avnet.com:zed:part0:1.1 em.avnet.com:zed:part0:1.3} \
     em.avnet.com:zed:part0:1.3
# Nothing from the same board: any board on the device, and say so loudly, which
# the script does.
pick "no same-board match, fall back" $zed \
     {xilinx.com:zc702:part0:1.4 xilinx.com:zc702:part0:1.3} \
     xilinx.com:zc702:part0:1.4
pick "nothing at all" $zed {} {}

if {$failures} {
    puts "\n$failures case(s) failed."
    exit 1
}
puts "\nall cases behaved as expected."
