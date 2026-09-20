# Check scripts/run_board_xsdb.tcl against a stand-in debugger.
#
#   python scripts/export_board_data.py --frames 512
#   tclsh scripts/test_run_board_xsdb.tcl
#
# Each case runs the real run script under scripts/_fake_xsdb_inner.tcl, which
# fakes xsdb's memory and register access. The good case must reach PASS; every
# fault case must stop with its own message rather than reporting a clean run on
# a broken one. Both spellings mrd uses for hex are covered.
#
# This does not test xsdb itself: connect, fpga, loadhw and ps7_init are stubs.
# It tests that the script's own logic and its guards are right.

set here   [file normalize [file dirname [info script]]]
set repo   [file dirname $here]
set inner  [file join $here _fake_xsdb_inner.tcl]

# case -> {prefix fault expected-substring}
set cases {
    {clean run, bare hex}      {0 none     "RESULT: PASS"}
    {clean run, 0x-prefix hex} {1 none     "RESULT: PASS"}
    {wrong bitstream}          {0 badid    "ID register reads"}
    {DDR not answering}        {0 ddr      "do not match this board"}
    {config stream cut short}  {0 cfgshort "configuration items, expected 73856"}
    {DMA reports an error}     {0 dmaerr   "DMA reported an error"}
    {results do not match}     {0 mismatch "RESULT: FAIL"}
    {no bulk memory read}      {0 nobulk   "RESULT: PASS"}
    {256 MB board}             {0 smallddr "RESULT: PASS"}
    {MMU on, SCTLR by name}    {0 mmusctlr    "RESULT: PASS"}
    {MMU on, name discovered}  {0 mmudiscover "RESULT: PASS"}
    {MMU on, no way to clear}  {0 mmu         "boot mode jumpers to JTAG"}
    {loadhw defines no ps7_init} {0 nops7        "RESULT: PASS"}
    {ps7_init nowhere to be found} {0 nops7missing "ps7_init is not defined"}
}

set failures 0
foreach {name spec} $cases {
    lassign $spec prefix fault want
    file delete -force [file join $repo build fake_xsdb_build]
    set rc [catch {exec [info nameofexecutable] $inner $repo $prefix $fault 2>@1} out]
    if {[string first $want $out] >= 0} {
        puts [format "  ok    %-26s %s" $name "-> $want"]
    } else {
        puts [format "  FAIL  %-26s expected '%s'" $name $want]
        puts "        got: [string range $out end-400 end]"
        incr failures
    }
}

# The blob-size guard needs a short file, so it gets its own case.
set gold [file join $repo build board gold.bin]
if {[file exists $gold]} {
    set keep [file join $repo build board gold.bin.keep]
    file copy -force $gold $keep
    set fh [open $keep rb]; fconfigure $fh -translation binary
    set short [read $fh 500000]; close $fh
    set fh [open $gold wb]; fconfigure $fh -translation binary
    puts -nonewline $fh $short; close $fh
    set rc [catch {exec [info nameofexecutable] $inner $repo 0 none 2>@1} out]
    file copy -force $keep $gold
    file delete $keep
    if {[string first "gold.bin is 500000 bytes, expected 524288" $out] >= 0} {
        puts [format "  ok    %-26s %s" "short data blob" "-> refuses to run"]
    } else {
        puts [format "  FAIL  %-26s %s" "short data blob" "ran anyway"]
        incr failures
    }
}

puts ""
if {$failures} {
    puts "$failures case(s) failed."
    exit 1
}
puts "all cases behaved as expected."
