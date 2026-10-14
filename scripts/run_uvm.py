"""Run the UVM bench in sim/uvm on Verilator or on the Vivado simulator (xsim).

    python scripts/run_uvm.py                       # every build, every test, 3 seeds
    python scripts/run_uvm.py --build small --test wm_random_test --seeds 10
    python scripts/run_uvm.py --sim xsim            # on a machine with Vivado
    python scripts/run_uvm.py --mutants             # prove the bench catches bugs

A run passes only when the test prints "WM_UVM_RESULT PASS" -- a UVM_FATAL ends
the simulation before that line, so a missing line is a failure, never a pass.
Results go to build/uvm/<sim>[_<uvm>]/: one log per test and seed, plus summary.json.

Verilator needs 5.040 or newer (UVM and covergroups), z3 for constrained
randomization, and the Accellera UVM sources: --uvm-home, or UVM_HOME. This
bench is checked on UVM 1.2 (the version xsim ships) and IEEE 1800.2-2020.3.1.
xsim needs nothing extra: Vivado ships UVM 1.2 precompiled (-L uvm).

--mutants copies the RTL, plants one known bug at a time, and requires every
mutant to FAIL at least one test. A bench that passes a broken design checks
nothing; this is how that is ruled out.

Python 3.9+ standard library only.
"""
import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UVM_DIR = ROOT/'sim'/'uvm'
RTL = ['rtl/overlapped_window_mac.sv', 'rtl/banked_window_mac.sv', 'rtl/window_mac_axis.sv']
BENCH = ['sim/uvm/wm_if.sv', 'sim/uvm/wm_uvm_pkg.sv']
TOP = 'sim/uvm/tb_top.sv'

# DUT builds. "board" is the bitstream the CIFAR network ran on
# (build_zedboard.tcl: CNN_K=1152 CNN_COUT=128 CNN_P=16 CNN_T=4 CNN_IMPL=3
# CNN_RUNTIME_GEOM=1, DEPTH default 2).
BUILDS = {
    'small': dict(KMAX=48,   COUTMAX=20,  P=4,  DEPTH=2, T=4, IMPL=3, RUNTIME_GEOM=1),
    'v3':    dict(KMAX=48,   COUTMAX=20,  P=4,  DEPTH=2, T=1, IMPL=2, RUNTIME_GEOM=1),
    'fixed': dict(KMAX=24,   COUTMAX=9,   P=2,  DEPTH=2, T=2, IMPL=3, RUNTIME_GEOM=0),
    'board': dict(KMAX=1152, COUTMAX=128, P=16, DEPTH=2, T=4, IMPL=3, RUNTIME_GEOM=1),
}
# Which tests each build runs, and the layer count of wm_random_test on it.
PLAN = {
    'small': (['wm_smoke_test', 'wm_reg_test', 'wm_random_test'], 150),
    'v3':    (['wm_smoke_test', 'wm_reg_test', 'wm_random_test'], 150),
    'fixed': (['wm_smoke_test', 'wm_reg_test', 'wm_random_test'], 40),
    'board': (['wm_smoke_test', 'wm_reg_test', 'wm_cifar_shapes_test', 'wm_random_test'], 4),
}

# Known bugs for --mutants: (name, file, original text, mutated text, what it breaks).
# Every original string must occur exactly once in its file.
MUTANTS = [
    ('relu_removed', 'rtl/banked_window_mac.sv',
     "results[d_slot][l]<=sum_next[l][31] ? 32'sd0 : sum_next[l];",
     "results[d_slot][l]<=sum_next[l];",
     'negative sums are emitted instead of clamped to 0'),
    # Not mutated: the wrapper's sign extension of weight beats into cfg_data[31:8].
    # Both cores store cfg_data[7:0] in a signed 8-bit RAM, so those bits are dead
    # and zero-extending them changes nothing -- an equivalent mutant, which the
    # first --mutants run reported as surviving. The sign is lost here instead:
    ('weight_sign_lost', 'rtl/banked_window_mac.sv',
     "weights[(cfg_channel/P)*ROWS+cfg_tap/T]<=cfg_data[7:0];",
     "weights[(cfg_channel/P)*ROWS+cfg_tap/T]<={1'b0, cfg_data[6:0]};",
     'negative INT8 weights are stored as positive'),
    ('lane1_reads_lane2', 'rtl/window_mac_axis.sv',
     "(sub==2'd1) ? beat[14:8]  :",
     "(sub==2'd1) ? beat[22:16] :",
     'the second activation of every beat is the third'),
    ('tlast_every_window', 'rtl/window_mac_axis.sv',
     "assign m_axis_tlast  = core_m_last && last_window;",
     "assign m_axis_tlast  = core_m_last;",
     'TLAST on the last channel of every window'),
    ('walker_ignores_run_k', 'rtl/window_mac_axis.sv',
     "if(cfg_tp==k_run-1) begin",
     "if(cfg_tp==K[NWP-1:0]-1) begin",
     'configuration walked at the built K, not RUN_K'),
    ('run_k_clamp_off_by_one', 'rtl/window_mac_axis.sv',
     "REG_RUN_K:    run_k   <=(s_axi_wdata==0 || s_axi_wdata>K)",
     "REG_RUN_K:    run_k   <=(s_axi_wdata==0 || s_axi_wdata>K+1)",
     'RUN_K accepts K+1'),
    ('done_one_window_early', 'rtl/window_mac_axis.sv',
     "wire last_window  = (win_done + 32'd1 == nwindows);",
     "wire last_window  = (win_done + 32'd2 == nwindows);",
     'the run ends, and TLAST comes, one window early'),
    ('in_stall_counts_idle', 'rtl/window_mac_axis.sv',
     "if(core_s_ready && !core_s_valid) in_stall<=in_stall+32'd1;",
     "if(!core_s_valid) in_stall<=in_stall+32'd1;",
     'IN_STALL counts cycles the core did not want input'),
    ('last_bias_dropped', 'rtl/banked_window_mac.sv',
     "if(rst_n && take_cfg && cfg_is_bias && cfg_channel<cout_eff && cfg_channel%P==lane)",
     "if(rst_n && take_cfg && cfg_is_bias && cfg_channel<cout_eff-1 && cfg_channel%P==lane)",
     'the last channel keeps the previous layer\'s bias'),
    ('sparse_drops_ones', 'rtl/banked_window_mac.sv',
     "wire store_input=take_input && (!mode || s_data!=0);",
     "wire store_input=take_input && (!mode || s_data>7'd1);",
     'sparse mode skips activations equal to 1 as if they were 0'),
]

RESULT_RE = re.compile(r'WM_UVM_RESULT (PASS|FAIL) test=(\S+) errors=(\d+) fatals=(\d+)')
SB_RE = re.compile(r'runs=(\d+) outputs_compared=(\d+) register_reads_checked=(\d+)')
COV_RE = re.compile(r'functional coverage: geometry ([\d.]+)%\s+mode x zeros ([\d.]+)%\s+'
                    r'data ([\d.]+)%\s+flow ([\d.]+)%')


def run(argv, cwd, log, timeout):
    t0 = time.time()
    try:
        proc = subprocess.run([str(a) for a in argv], cwd=cwd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, errors='replace',
                              timeout=timeout)
        out, rc = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b'').decode('utf-8', 'replace') if isinstance(e.stdout, bytes) \
              else (e.stdout or '')
        out += f'\n*** run_uvm.py: timed out after {timeout} s\n'
        rc = -1
    Path(log).write_text(out, encoding='utf-8')
    return rc, out, time.time()-t0


# ----------------------------------------------------------------- simulators
class Verilator:
    name = 'verilator'

    def __init__(self, exe, uvm_home, jobs):
        self.exe, self.uvm_home, self.jobs = exe, Path(uvm_home), jobs

    def compile(self, build, params, dest, src_root):
        dest.mkdir(parents=True, exist_ok=True)
        obj = dest/'obj'
        argv = [self.exe, '--binary', '-j', str(self.jobs), '--assert', '-Wno-fatal', '-Wno-lint',
                '-Wno-style', '--timescale', '1ns/1ps', '--top-module', 'tb_top',
                f'+incdir+{self.uvm_home/"src"}', '+define+UVM_NO_DPI',
                f'+incdir+{src_root/"sim"/"uvm"}', '-Mdir', obj]
        argv += [f'-G{k}={v}' for k, v in params.items()]
        argv += [self.uvm_home/'src'/'uvm_pkg.sv']
        argv += [src_root/f for f in BENCH+RTL+[TOP]]
        rc, out, sec = run(argv, dest, dest/'compile.log', 3600)
        if rc:
            raise RuntimeError(f'{build}: Verilator compile failed, see {dest/"compile.log"}\n'
                               + '\n'.join(l for l in out.splitlines() if '%Error' in l)[:4000])
        return sec

    def sim(self, dest, test, seed, plusargs, log, timeout):
        argv = [dest/'obj'/'Vtb_top', f'+UVM_TESTNAME={test}', f'+verilator+seed+{seed}']
        argv += [f'+{p}' for p in plusargs]
        return run(argv, dest, log, timeout)


class Xsim:
    name = 'xsim'

    def __init__(self, bindir):
        self.bindir = Path(bindir)

    def tool(self, n):
        for cand in (n+'.bat', n):
            p = self.bindir/cand
            if p.exists():
                return p
        raise SystemExit(f'{n} not found in {self.bindir}')

    def compile(self, build, params, dest, src_root):
        dest.mkdir(parents=True, exist_ok=True)
        files = [src_root/f for f in BENCH+RTL+[TOP]]
        t0 = time.time()
        rc, out, _ = run([self.tool('xvlog'), '-sv', '-L', 'uvm', '-i', src_root/'sim'/'uvm',
                          '--log', dest/'xvlog.log'] + files, dest, dest/'xvlog.out', 3600)
        if rc:
            raise RuntimeError(f'{build}: xvlog failed, see {dest/"xvlog.log"}\n{out[-4000:]}')
        argv = [self.tool('xelab'), '-L', 'uvm', '-timescale', '1ns/1ps', 'tb_top',
                '-s', f'wm_{build}', '--log', dest/'xelab.log']
        for k, v in params.items():
            argv += ['-generic_top', f'{k}={v}']
        rc, out, _ = run(argv, dest, dest/'xelab.out', 3600)
        if rc:
            raise RuntimeError(f'{build}: xelab failed, see {dest/"xelab.log"}\n{out[-4000:]}')
        return time.time()-t0

    def sim(self, dest, test, seed, plusargs, log, timeout):
        # The snapshot is named after the build, which is the directory name.
        argv = [self.tool('xsim'), f'wm_{dest.name}', '-runall', '-sv_seed', str(seed),
                '-testplusarg', f'UVM_TESTNAME={test}']
        for p in plusargs:
            argv += ['-testplusarg', p]
        argv += ['--log', Path(log).with_suffix('.xsim.log')]
        return run(argv, dest, log, timeout)


def find_vivado_bin():
    """Vivado's bin directory: PATH, XILINX_VIVADO, then the roots find_vivado.cmd searches."""
    p = shutil.which('xvlog')
    if p:
        return Path(p).parent
    if os.environ.get('XILINX_VIVADO'):
        b = Path(os.environ['XILINX_VIVADO'])/'bin'
        if b.exists():
            return b
    roots = [r'C:\Xilinx', r'D:\Xilinx', r'E:\Xilinx', r'C:\Vivado', r'D:\Vivado', r'E:\Vivado',
             r'C:\tools\Xilinx', r'C:\AMD', r'D:\AMD', '/opt/Xilinx', '/tools/Xilinx']
    for r in map(Path, roots):
        if not r.exists():
            continue
        for v in sorted((d for d in r.iterdir() if d.is_dir()), reverse=True):
            for b in (v/'Vivado'/'bin', v/'bin'):          # <root>\<ver>\Vivado, <root>\Vivado\<ver>
                if (b/'xvlog.bat').exists() or (b/'xvlog').exists():
                    return b
        vroot = r/'Vivado'
        if vroot.exists():
            for v in sorted((d for d in vroot.iterdir() if d.is_dir()), reverse=True):
                if (v/'bin'/'xvlog.bat').exists() or (v/'bin'/'xvlog').exists():
                    return v/'bin'
    return None


def pick_sim(args):
    if args.sim in (None, 'verilator'):
        exe = args.verilator or shutil.which('verilator')
        uvm = args.uvm_home or os.environ.get('UVM_HOME')
        if exe and uvm:
            if not (Path(uvm)/'src'/'uvm_pkg.sv').exists():
                raise SystemExit(f'--uvm-home {uvm}: no src/uvm_pkg.sv there')
            return Verilator(exe, uvm, args.jobs)
        if args.sim == 'verilator':
            raise SystemExit('Verilator needs the executable on PATH (or --verilator) and the '
                             'Accellera UVM sources (--uvm-home or UVM_HOME).')
    b = Path(args.vivado_bin) if args.vivado_bin else find_vivado_bin()
    if b is None:
        raise SystemExit('No simulator found. Install Vivado (xsim) or pass --sim verilator '
                         'with --verilator and --uvm-home.')
    return Xsim(b)


# ---------------------------------------------------------------------- runs
def parse(out):
    m = RESULT_RE.search(out)
    r = dict(result='FAIL', errors=None, fatals=None)
    if m:
        r.update(result=m.group(1), errors=int(m.group(3)), fatals=int(m.group(4)))
    if re.search(r'UVM_FATAL\s*:\s*[1-9]', out) or re.search(r'UVM_ERROR\s*:\s*[1-9]', out):
        r['result'] = 'FAIL'
    m = SB_RE.search(out)
    if m:
        r.update(runs=int(m.group(1)), outputs=int(m.group(2)), reg_reads=int(m.group(3)))
    m = COV_RE.search(out)
    if m:
        r['coverage'] = dict(zip(('geometry', 'mode_x_zeros', 'data', 'flow'),
                                 map(float, m.groups())))
    first = [l for l in out.splitlines() if re.match(r'\s*(UVM_ERROR|UVM_FATAL) \S', l)]
    if first:
        r['first_error'] = first[0].strip()[:300]
    if r['result'] == 'FAIL' and 'first_error' not in r:
        r['first_error'] = (out.strip().splitlines() or ['(no output)'])[-1][:300]
    return r


def run_build(sim, build, tests, seeds, layers, out_root, src_root, timeout, quiet=False):
    dest = out_root/build
    if dest.exists():
        shutil.rmtree(dest)
    sec = sim.compile(build, BUILDS[build], dest, src_root)
    if not quiet:
        print(f'  [{build}] compiled in {sec:.0f} s', flush=True)
    rows = []
    for test in tests:
        for seed in seeds:
            plus = [f'WM_LAYERS={layers}'] if test == 'wm_random_test' else []
            log = dest/f'{test}_s{seed}.log'
            rc, out, s = sim.sim(dest, test, seed, plus, log, timeout)
            r = parse(out)
            if rc not in (0,) and r['result'] == 'PASS':
                r['result'] = 'FAIL'
                r['first_error'] = f'simulator exited with {rc}'
            r.update(build=build, test=test, seed=seed, seconds=round(s, 1),
                     log=str(log.relative_to(ROOT)) if log.is_relative_to(ROOT) else str(log))
            rows.append(r)
            if not quiet:
                extra = ''
                if 'outputs' in r:
                    extra = f"outputs={r['outputs']} runs={r['runs']} reg_reads={r['reg_reads']}"
                if r['result'] != 'PASS':
                    extra += f"  <- {r.get('first_error', '')}"
                print(f"  [{build}] {test:<22} seed {seed:<4} {r['result']}  {s:6.1f}s  {extra}",
                      flush=True)
    return rows


def out_name(sim):
    # One directory per simulator and UVM version, so a 1.2 run and a 2020 run
    # do not overwrite each other: build/uvm/verilator_uvm-1.2, build/uvm/xsim.
    if isinstance(sim, Verilator):
        return f'verilator_{sim.uvm_home.name}'
    return sim.name


def main_suite(args, sim):
    out_root = ROOT/'build'/'uvm'/out_name(sim)
    out_root.mkdir(parents=True, exist_ok=True)
    builds = args.build or list(BUILDS)
    seeds = list(range(1, args.seeds+1)) if args.seed is None else [args.seed]
    print(f'simulator: {sim.name}' + (f'  UVM: {sim.uvm_home}' if isinstance(sim, Verilator) else
                                      f'  ({sim.bindir})'))
    rows = []
    # Builds compile and run independently; Verilator compiles are the slow part.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {}
        for b in builds:
            tests, layers = PLAN[b]
            if args.test:
                tests = [t for t in args.test]
            if args.layers:
                layers = args.layers
            futs[ex.submit(run_build, sim, b, tests, seeds, layers, out_root, ROOT,
                           args.timeout)] = b
        for f in concurrent.futures.as_completed(futs):
            rows += f.result()
    rows.sort(key=lambda r: (builds.index(r['build']), r['test'], r['seed']))
    failed = [r for r in rows if r['result'] != 'PASS']
    summary = dict(simulator=sim.name,
                   uvm=str(getattr(sim, 'uvm_home', 'Vivado built-in UVM 1.2')),
                   builds={b: BUILDS[b] for b in builds},
                   passed=len(rows)-len(failed), failed=len(failed),
                   outputs_compared=sum(r.get('outputs', 0) for r in rows),
                   register_reads_checked=sum(r.get('reg_reads', 0) for r in rows),
                   runs=rows)
    (out_root/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f"\n{summary['passed']}/{len(rows)} passed, {summary['outputs_compared']} outputs and "
          f"{summary['register_reads_checked']} register reads checked -> {out_root/'summary.json'}")
    for r in failed:
        print(f"  FAIL {r['build']} {r['test']} seed {r['seed']}: {r.get('first_error')}  ({r['log']})")
    return 1 if failed else 0


def main_mutants(args, sim):
    if not isinstance(sim, Verilator):
        raise SystemExit('--mutants is wired for Verilator only')
    out_root = ROOT/'build'/'uvm'/'mutants'
    if out_root.exists():
        shutil.rmtree(out_root)
    tests = ['wm_smoke_test', 'wm_reg_test', 'wm_random_test']
    seeds = [1, 2]

    def one(m):
        name, rel, old, new, what = m
        src = out_root/name/'src'
        for d in ('rtl', 'sim'):
            shutil.copytree(ROOT/d, src/d)
        f = src/rel
        text = f.read_text(encoding='utf-8')
        if text.count(old) != 1:
            raise RuntimeError(f'mutant {name}: original text found {text.count(old)} times in {rel}')
        f.write_text(text.replace(old, new), encoding='utf-8')
        rows = run_build(sim, 'small', tests, seeds, 12, out_root/name, src, args.timeout, quiet=True)
        killed = [r for r in rows if r['result'] != 'PASS']
        return name, what, rows, killed

    survivors = []
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        for name, what, rows, killed in ex.map(one, MUTANTS):
            by = sorted({f"{r['test']}" for r in killed})
            first = killed[0].get('first_error', '') if killed else ''
            print(f"  {'KILLED  ' if killed else 'SURVIVED'} {name:<24} {what}")
            if killed:
                print(f"           caught by {', '.join(by)}: {first[:160]}")
            else:
                survivors.append(name)
            results.append(dict(mutant=name, breaks=what, killed=bool(killed), caught_by=by,
                                first_error=first))
    (out_root/'summary.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f'\n{len(MUTANTS)-len(survivors)}/{len(MUTANTS)} mutants killed -> {out_root/"summary.json"}')
    return 1 if survivors else 0


def main_report(args):
    """Write sim/uvm/RESULTS_UVM_KO.md from the summary.json files under build/uvm."""
    base = ROOT/'build'/'uvm'
    suites = sorted(p for p in base.glob('*/summary.json') if p.parent.name != 'mutants')
    if not suites:
        raise SystemExit(f'no results under {base}: run the suite first')
    ver = ''
    exe = args.verilator or shutil.which('verilator')
    if exe:
        ver = subprocess.run([exe, '--version'], stdout=subprocess.PIPE, text=True).stdout.strip()
    L = ['# UVM 검증 결과', '',
         f'`python scripts/run_uvm.py --report`가 `build/uvm/*/summary.json`에서 생성했습니다. '
         '손으로 옮겨 적은 숫자는 없습니다.', '']
    if ver:
        L += [f'Verilator: `{ver}`', '']
    for p in suites:
        d = json.loads(p.read_text(encoding='utf-8'))
        rows = d['runs']
        L += [f'## {p.parent.name}  —  UVM: `{Path(d["uvm"]).name}`', '',
              f'**{d["passed"]}/{d["passed"]+d["failed"]} 통과**, 출력 {d["outputs_compared"]:,}개, '
              f'레지스터 읽기 {d["register_reads_checked"]:,}개 비교.', '',
              '| 빌드 | 테스트 | 시드 | 결과 | 비교한 출력 | 레지스터 읽기 | 커버리지 (형상 / 모드×0 / 데이터 / 흐름) |',
              '|---|---|---|---|---|---|---|']
        keys = []
        for r in rows:
            k = (r['build'], r['test'])
            if k not in keys:
                keys.append(k)
        for b, t in keys:
            rs = [r for r in rows if r['build'] == b and r['test'] == t]
            ok = sum(r['result'] == 'PASS' for r in rs)
            cov = [r['coverage'] for r in rs if 'coverage' in r]
            c = ''
            if cov:
                c = ' / '.join(f"{min(x[f] for x in cov):.0f}–{max(x[f] for x in cov):.0f}%"
                               if min(x[f] for x in cov) != max(x[f] for x in cov)
                               else f"{cov[0][f]:.0f}%"
                               for f in ('geometry', 'mode_x_zeros', 'data', 'flow'))
            L.append(f"| {b} | {t} | {','.join(str(r['seed']) for r in rs)} | {ok}/{len(rs)} | "
                     f"{sum(r.get('outputs', 0) for r in rs):,} | {sum(r.get('reg_reads', 0) for r in rs):,} | {c} |")
        fails = [r for r in rows if r['result'] != 'PASS']
        for r in fails:
            L.append(f"\n실패: {r['build']} {r['test']} seed {r['seed']}: `{r.get('first_error', '')}`")
        L.append('')
    L += ['### 커버리지 읽는 법', '',
          '- 커버리지는 시뮬레이션 1회 안에서 계산합니다. 시드끼리 합치지 않습니다. 표는 시드별 값의 최소–최대입니다.',
          '- smoke / reg / cifar_shapes는 정해진 레이어 몇 개만 돌리므로 낮은 것이 정상입니다. 랜덤 테스트의 숫자가 의미 있는 값입니다.',
          '- **fixed** 빌드는 형상이 고정(K=24, COUT=9)이라 형상 칸 25개 중 1개 조합만 존재합니다. 9%가 최대입니다.',
          '- **v3**는 bank가 없어서(T=1) "K가 bank 수의 배수가 아님" 칸에 도달할 수 없습니다. 형상 최대가 100%가 아닙니다.',
          '- **board**의 랜덤 테스트는 레이어가 크기 때문에(K≤1152) 4개만 돌립니다. 형상 칸을 채우는 역할은 small 빌드가 맡습니다.',
          '']
    m = base/'mutants'/'summary.json'
    if m.exists():
        ms = json.loads(m.read_text(encoding='utf-8'))
        killed = sum(x['killed'] for x in ms)
        L += ['## 뮤턴트 (일부러 심은 버그)', '',
              f'**{killed}/{len(ms)} 검출.** small 빌드에서 smoke / reg / random(12 레이어) × 시드 2개를 돌려, '
              '하나라도 FAIL이면 "검출"입니다.', '',
              '| 뮤턴트 | 깨지는 것 | 결과 | 잡은 테스트 |', '|---|---|---|---|']
        for x in ms:
            L.append(f"| `{x['mutant']}` | {x['breaks']} | {'검출' if x['killed'] else '**놓침**'} | "
                     f"{', '.join(x['caught_by'])} |")
        L.append('')
    out = UVM_DIR/'RESULTS_UVM_KO.md'
    out.write_text('\n'.join(L), encoding='utf-8')
    print(f'wrote {out}')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sim', choices=['verilator', 'xsim'])
    ap.add_argument('--verilator', help='verilator executable (default: on PATH)')
    ap.add_argument('--uvm-home', help='Accellera UVM source tree, for Verilator')
    ap.add_argument('--vivado-bin', help='Vivado bin directory, for xsim')
    ap.add_argument('--build', action='append', choices=list(BUILDS))
    ap.add_argument('--test', action='append')
    ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--seed', type=int, help='run this one seed only')
    ap.add_argument('--layers', type=int, help='layers in wm_random_test')
    ap.add_argument('--jobs', type=int, default=os.cpu_count() or 2, help='Verilator -j')
    ap.add_argument('--parallel', type=int, default=2, help='builds at once')
    ap.add_argument('--timeout', type=int, default=3600, help='seconds per simulation')
    ap.add_argument('--mutants', action='store_true')
    ap.add_argument('--report', action='store_true',
                    help='write sim/uvm/RESULTS_UVM_KO.md from the results already in build/uvm')
    args = ap.parse_args()
    if args.report:
        sys.exit(main_report(args))
    sim = pick_sim(args)
    sys.exit(main_mutants(args, sim) if args.mutants else main_suite(args, sim))


if __name__ == '__main__':
    main()
