// UVM verification environment for window_mac_axis.
// See sim/uvm/README_KO.md for the structure and how to run it.
`include "uvm_macros.svh"
package wm_uvm_pkg;
    import uvm_pkg::*;
    `include "wm_cfg.svh"
    `include "wm_axil_agent.svh"
    `include "wm_axis_agent.svh"
    `include "wm_scoreboard.svh"
    `include "wm_coverage.svh"
    `include "wm_seqs.svh"
    `include "wm_env.svh"
    `include "wm_tests.svh"
endpackage
