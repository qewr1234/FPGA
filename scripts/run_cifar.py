"""Run the whole quantized CIFAR-10 network on the board, one layer at a time.

The accelerator computes one thing: bias + sum(activation * weight), then ReLU,
for a window of K activations against COUT channels. A convolution layer is that
applied to every output position, so a layer is im2col on the host and one board
run. Everything between layers -- requantizing INT32 accumulators back to the
0..127 the input port takes, and max pooling -- is host arithmetic, and so is the
global average pool and the classifier at the end.

Layer N+1's input is layer N's output, so the layers cannot run in parallel. What
CAN be batched is images: every image needs the same six shapes in the same
order, so a batch of images is six board runs, not six per image. That matters,
because each board run costs a bitstream load over JTAG.

Requires ONE bitstream, built with runtime geometry on and memories large enough
for the widest layer:

    set CNN_K=1152 & set CNN_COUT=128 & set CNN_RUNTIME_GEOM=1
    vivado -mode batch -source scripts/build_zedboard.tcl

Then:

    python scripts/run_cifar.py --emulate            # host only, no board
    python scripts/run_cifar.py --xsdb C:/Vivado/2026.1/Vivado/bin/xsdb.bat \
                                --build build/zed_v3_p8_t4_... --images 16

--emulate computes what the board would compute and carries that forward, so the
whole pipeline -- window order, file layout, requantization, pooling, the
classifier -- can be checked without hardware. It is not evidence about the
hardware; only a real run is that, and a real run says so in its report.

Reads cifar/export/ (manifest.json + conv<N>_config.bin) from quantize_cifar.py,
and the CIFAR-10 test batch torchvision downloaded. Writes build/board/ per layer
and build/cifar_run/report.json at the end.
"""
import argparse
import json
import pickle
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# Where this run's blobs go. Not build/board, so a network run does not overwrite
# the single-layer export sitting there; run_board_xsdb.tcl is pointed at it with
# WM_BOARD_DIR. main() may move it elsewhere on request.
BOARD = ROOT/'build'/'cifar_board'
QMAX_A = 127


# ----------------------------------------------------------------- windows ---
def im2col(q, kh=3, kw=3, pad=1):
    """(B, C, H, W) activations -> (B*H*W, K) windows in tap order (ky, kx, cin).

    Tap index is (ky*kw + kx)*C + c, which is the order quantize_cifar.py lays
    the weights out in and the order export_featuremap.py proved against the
    VGG config.bin. Output positions run row-major within an image, images in
    order, which is the order the core emits results in.
    """
    b, c, h, w = q.shape
    padded = np.zeros((b, c, h+2*pad, w+2*pad), q.dtype)
    padded[:, :, pad:pad+h, pad:pad+w] = q
    cols = np.stack([padded[:, :, ky:ky+h, kx:kx+w]
                     for ky in range(kh) for kx in range(kw)], axis=1)
    # (B, ky*kx, C, H, W) -> (B, H, W, ky*kx, C) -> (B*H*W, K)
    return cols.transpose(0, 3, 4, 1, 2).reshape(b*h*w, kh*kw*c)


def im2col_reference(q, kh=3, kw=3, pad=1):
    """The same thing written as explicit loops, for the self test.

    Deliberately not sharing a line with im2col: two implementations that agree
    is evidence, one implementation compared with itself is not.
    """
    b, c, h, w = q.shape
    out = np.zeros((b*h*w, kh*kw*c), q.dtype)
    for bi in range(b):
        for oy in range(h):
            for ox in range(w):
                row = out[(bi*h + oy)*w + ox]
                for ky in range(kh):
                    for kx in range(kw):
                        iy, ix = oy + ky - pad, ox + kx - pad
                        if 0 <= iy < h and 0 <= ix < w:
                            base = (ky*kw + kx)*c
                            row[base:base+c] = q[bi, :, iy, ix]
    return out


def oracle(x, w, b):
    """ReLU(bias + sum(a*w)) in INT32 -- exactly what the core computes."""
    y = x.astype(np.int64) @ w.astype(np.int64).T + b.astype(np.int64)
    y = np.maximum(0, y)
    if y.max() > 2**31 - 1:
        raise SystemExit(f'accumulator overflows INT32 ({y.max():,}). The '
                         f'quantization is wrong, not the run.')
    return y.astype(np.int32)


def requant(acc, factors):
    """INT32 accumulators -> the 0..127 the next layer's input port takes."""
    return np.clip(np.rint(acc*factors), 0, QMAX_A).astype(np.uint8)


def maxpool2(q):
    """(B, C, H, W) -> (B, C, H/2, W/2), the pooling folded into the host side."""
    b, c, h, w = q.shape
    if h % 2 or w % 2:
        raise SystemExit(f'cannot 2x2 pool a {h}x{w} map')
    return q.reshape(b, c, h//2, 2, w//2, 2).max(axis=(3, 5))


# -------------------------------------------------------------- board files ---
def write_board_files(cfg_src, x, gold, mode_seq):
    """Lay out what run_board_xsdb.tcl loads, and say what the run will be.

    config.bin is copied rather than rebuilt: it is the exporter's output, and
    the one thing in this pipeline that must be byte-identical to what was
    verified. input.bin is the windows as raw bytes -- the wrapper takes four
    activations per 32-bit beat, low byte first, which is just this order.
    """
    n, k = x.shape
    cout = gold.shape[1]
    if n*k % 4:
        raise SystemExit(f'{n} windows of {k} taps is {n*k} activations, which '
                         f'does not pack into whole 32-bit beats')
    BOARD.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cfg_src, BOARD/'config.bin')
    (BOARD/'input.bin').write_bytes(np.ascontiguousarray(x, np.uint8).tobytes())
    (BOARD/'gold.bin').write_bytes(gold.astype('<i4').tobytes())
    (BOARD/'run.json').unlink(missing_ok=True)
    (BOARD/'results.bin').unlink(missing_ok=True)
    layout = dict(split='cifar', K=int(k), COUT=int(cout),
                  frames=int(n), windows=int(n), mode_seq=int(mode_seq),
                  config_words=(BOARD/'config.bin').stat().st_size//4,
                  input_words=n*k//4, gold_words=n*cout,
                  addresses={'config': '0x10000000', 'input': '0x10100000',
                             'result': '0x10200000', 'gold': '0x10300000'})
    (BOARD/'layout.json').write_text(json.dumps(layout, indent=2)+'\n', encoding='utf-8')
    return layout


def run_board(xsdb, build, log_path):
    """One xsdb session: load the bitstream, run this layer, read the results.

    The run script is sourced rather than rewritten. It is the only part of this
    that has been proven on the board, and an error inside it must end the
    process rather than drop xsdb to an interactive prompt nobody is watching.
    """
    wrapper = BOARD/'_run_layer.tcl'
    lines = [f'set ::env(WM_BOARD_DIR) {{{BOARD.resolve().as_posix()}}}']
    if build:
        lines.append(f'set ::env(WM_BUILD) {{{Path(build).resolve().as_posix()}}}')
    lines += [f'set _rc [catch {{source {(ROOT/"scripts"/"run_board_xsdb.tcl").as_posix()}}} _err]',
              'if {$_rc} { puts "ERROR: $_err" ; exit 1 }',
              'exit 0']
    wrapper.write_text('\n'.join(lines)+'\n', encoding='utf-8')

    started = time.time()
    proc = subprocess.run([str(xsdb), str(wrapper)], cwd=str(ROOT),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log_path.write_text(proc.stdout, encoding='utf-8')
    run_json = BOARD/'run.json'
    if proc.returncode or not run_json.exists():
        raise SystemExit(f'the board run failed (exit {proc.returncode}). '
                         f'Full output: {log_path}\n'
                         + '\n'.join(proc.stdout.splitlines()[-25:]))
    info = json.loads(run_json.read_text())
    info['wall_seconds'] = round(time.time()-started, 1)
    if info['mismatches']:
        raise SystemExit(f'{info["mismatches"]} results differ from the host '
                         f'oracle, first at word {info["first_bad_word"]}. '
                         f'Full output: {log_path}')
    return info


def board_results(n, cout):
    """What the hardware actually produced, not what it was supposed to."""
    raw = (BOARD/'results.bin').read_bytes()
    if len(raw) != n*cout*4:
        raise SystemExit(f'results.bin is {len(raw)} bytes, expected {n*cout*4}')
    return np.frombuffer(raw, '<i4').reshape(n, cout)


# ------------------------------------------------------------------- inputs ---
def load_cifar_test(data_dir, count):
    """The CIFAR-10 test batch, straight from the file torchvision downloaded.

    Read with pickle and numpy so this runs on a machine with no torch -- the
    board machine needs xsdb, not a training stack.
    """
    batch = Path(data_dir)/'cifar-10-batches-py'/'test_batch'
    if not batch.exists():
        raise SystemExit(f'{batch} not found. Run cifar/quantize_cifar.py once '
                         f'on this machine, or copy cifar/data/ across.')
    with open(batch, 'rb') as fh:
        d = pickle.load(fh, encoding='bytes')
    images = d[b'data'][:count].reshape(-1, 3, 32, 32).astype(np.float64)/255.0
    labels = np.asarray(d[b'labels'][:count], np.int64)
    return images, labels


def classify(q, manifest):
    """Global average pool, back to float, then the host's linear classifier."""
    feat = q.mean(axis=(2, 3))*manifest['fc_input_scale']
    logits = feat @ np.asarray(manifest['fc_weight']).T + np.asarray(manifest['fc_bias'])
    return logits.argmax(1)


# -------------------------------------------------------------------- main ---
def selftest():
    """Check the pieces against independent implementations, on shapes that
    match the real network. No board, no checkpoint, no torch."""
    rng = np.random.default_rng(20260922)
    print('im2col against an explicit loop:')
    for b, c, h in [(2, 3, 8), (3, 32, 6), (1, 64, 4)]:
        q = rng.integers(0, 128, (b, c, h, h), dtype=np.uint8)
        a, r = im2col(q), im2col_reference(q)
        assert a.shape == (b*h*h, 9*c) and np.array_equal(a, r), (b, c, h)
        print(f'  ({b}, {c}, {h}, {h}) -> {a.shape}  identical')

    print('\nim2col places the taps where the weights expect them:')
    # A weight vector that is 1 at exactly one tap picks out exactly one input
    # pixel, so the mapping can be read off rather than argued about.
    q = rng.integers(0, 128, (1, 5, 6, 6), dtype=np.uint8)
    cols = im2col(q)
    for ky, kx, c in [(0, 0, 0), (1, 1, 3), (2, 1, 4), (0, 2, 2)]:
        tap = (ky*3 + kx)*5 + c
        got = cols[:, tap].reshape(6, 6)
        want = np.zeros((6, 6), np.int64)
        for oy in range(6):
            for ox in range(6):
                iy, ix = oy+ky-1, ox+kx-1
                if 0 <= iy < 6 and 0 <= ix < 6:
                    want[oy, ox] = q[0, c, iy, ix]
        assert np.array_equal(got, want), (ky, kx, c)
        print(f'  tap {tap:>3} = (ky={ky}, kx={kx}, cin={c})  ok')

    print('\nmaxpool against an explicit loop:')
    q = rng.integers(0, 128, (2, 7, 8, 8), dtype=np.uint8)
    p = maxpool2(q)
    want = np.zeros_like(p)
    for bi in range(2):
        for ci in range(7):
            for y in range(4):
                for x in range(4):
                    want[bi, ci, y, x] = q[bi, ci, 2*y:2*y+2, 2*x:2*x+2].max()
    assert np.array_equal(p, want)
    print(f'  {q.shape} -> {p.shape}  identical')

    print('\noracle keeps the ReLU and the INT32 bound:')
    x = rng.integers(0, 128, (64, 27), dtype=np.uint8)
    w = rng.integers(-128, 128, (32, 27), dtype=np.int8)
    b = rng.integers(-10000, 10000, 32, dtype=np.int32)
    y = oracle(x, w, b)
    assert y.min() >= 0 and y.dtype == np.int32
    slow = np.array([[max(0, int(b[c]) + int(sum(int(a)*int(v) for a, v in zip(row, w[c]))))
                      for c in range(32)] for row in x[:8]], np.int64)
    assert np.array_equal(y[:8], slow)
    print(f'  {y.shape}, min {y.min()}, max {y.max():,}  matches the slow form')

    print('\nlayer chain on synthetic weights, end to end:')
    _selftest_chain(rng)
    print('\nSELFTEST PASS')


def _selftest_chain(rng):
    """The driver's per-layer loop against one written straight through.

    This is the check that matters: the pipeline splits a network into six
    independent board runs and stitches the results back together, and a
    stitching bug looks exactly like a working run with poor accuracy.
    """
    convs = [(3, 8), (8, 8), (8, 16), (16, 16), (16, 24), (24, 24)]
    layers, ws, bs = [], [], []
    for i, (cin, cout) in enumerate(convs):
        k = 9*cin
        ws.append(rng.integers(-128, 128, (cout, k), dtype=np.int8))
        bs.append(rng.integers(-5000, 5000, cout, dtype=np.int32))
        layers.append(dict(name=f'conv{i+1}', K=k, COUT=cout, pool_after=(i % 2 == 1),
                           requant=list(rng.uniform(0.002, 0.02, cout))))

    q0 = rng.integers(0, 128, (3, 3, 16, 16), dtype=np.uint8)

    # the driver's way: one layer at a time, through the same helpers a board
    # run goes through
    q = q0
    for L, w, b in zip(layers, ws, bs):
        b_, c_, h_, w_ = q.shape
        x = im2col(q, kh=3, kw=3)
        acc = oracle(x, w, b)
        nxt = requant(acc, np.asarray(L['requant']))
        q = nxt.reshape(b_, h_, w_, L['COUT']).transpose(0, 3, 1, 2)
        if L['pool_after']:
            q = maxpool2(q)

    # the straight-through way, written without the helpers
    ref = q0.astype(np.int64)
    for L, w, b in zip(layers, ws, bs):
        bn, cn, hn, wn = ref.shape
        pad = np.zeros((bn, cn, hn+2, wn+2), np.int64)
        pad[:, :, 1:hn+1, 1:wn+1] = ref
        out = np.zeros((bn, L['COUT'], hn, wn), np.int64)
        r = np.asarray(L['requant'])
        for bi in range(bn):
            for oy in range(hn):
                for ox in range(wn):
                    win = pad[bi, :, oy:oy+3, ox:ox+3].transpose(1, 2, 0).reshape(-1)
                    acc = np.maximum(0, win @ w.T.astype(np.int64) + b)
                    out[bi, :, oy, ox] = np.clip(np.rint(acc*r), 0, QMAX_A)
        ref = out
        if L['pool_after']:
            bn, cn, hn, wn = ref.shape
            ref = ref.reshape(bn, cn, hn//2, 2, wn//2, 2).max(axis=(3, 5))
    assert q.shape == ref.shape, (q.shape, ref.shape)
    assert np.array_equal(q.astype(np.int64), ref), 'the split pipeline drifted'
    print(f'  6 layers, {q0.shape} -> {q.shape}  identical to the straight form')


def main():
    global BOARD
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--export', type=Path, default=ROOT/'cifar'/'export',
                    help='quantize_cifar.py output: manifest.json + conv*_config.bin')
    ap.add_argument('--data', type=Path, default=ROOT/'cifar'/'data',
                    help='where torchvision put cifar-10-batches-py')
    ap.add_argument('--images', type=int, default=16,
                    help='test images per batch. Every image costs JTAG time.')
    ap.add_argument('--xsdb', type=Path, help='path to xsdb (or xsdb.bat)')
    ap.add_argument('--build', type=Path,
                    help='bitstream directory; defaults to the newest build/zed_*')
    ap.add_argument('--emulate', action='store_true',
                    help='no board: compute what it would compute and carry that on')
    ap.add_argument('--mode', type=int, default=1, choices=[0, 1],
                    help='0 dense, 1 sparse (skip zero activations). Same results.')
    ap.add_argument('--out', type=Path, default=ROOT/'build'/'cifar_run')
    ap.add_argument('--board-dir', type=Path,
                    help='where this run stages config/input/gold for the board '
                         f'(default {BOARD.relative_to(ROOT)})')
    ap.add_argument('--selftest', action='store_true',
                    help='check the host arithmetic and exit')
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    if args.board_dir:
        BOARD = args.board_dir.resolve()
    if not args.emulate and not args.xsdb:
        raise SystemExit('give --xsdb to run on the board, or --emulate to run '
                         'the host side alone.')

    manifest = json.loads((args.export/'manifest.json').read_text())
    layers = manifest['layers']
    images, labels = load_cifar_test(args.data, args.images)
    print(f'{len(images)} test images, {len(layers)} convolutions, '
          f'K up to {manifest["K_MAX"]}, COUT up to {manifest["COUT_MAX"]}')
    print(f'mode: {"sparse (zero activations skipped)" if args.mode else "dense"}')
    print(f'{"emulating the board" if args.emulate else "running on the board"}\n')

    args.out.mkdir(parents=True, exist_ok=True)
    a0 = layers[0]['a_scale_in']
    q = np.clip(np.rint(images/a0), 0, QMAX_A).astype(np.uint8)

    runs, total_cycles = [], 0
    for L in layers:
        b, c, h, w = q.shape
        x = im2col(q)
        if x.shape[1] != L['K']:
            raise SystemExit(f'{L["name"]}: windows are {x.shape[1]} taps but the '
                             f'weights are {L["K"]}. The network and the export '
                             f'do not describe the same model.')
        blob = np.frombuffer((args.export/L['config']).read_bytes(), '<i4')
        wq = blob[:L['COUT']*L['K']].reshape(L['COUT'], L['K']).astype(np.int8)
        bq = blob[L['COUT']*L['K']:].astype(np.int32)
        gold = oracle(x, wq, bq)

        layout = write_board_files(args.export/L['config'], x, gold, args.mode)
        nz = float((x != 0).mean())
        print(f'{L["name"]}: {x.shape[0]:>6} windows x K={L["K"]:>4} -> COUT={L["COUT"]:>3}'
              f'   {nz*100:5.1f}% nonzero   '
              f'{(layout["input_words"]+layout["gold_words"]+layout["config_words"])*4/1e6:5.2f} MB')

        if args.emulate:
            acc = gold
            info = dict(emulated=True, windows_done=x.shape[0], mismatches=0)
        else:
            info = run_board(args.xsdb, args.build, args.out/f'{L["name"]}_xsdb.log')
            acc = board_results(x.shape[0], L['COUT'])
            total_cycles += info['cycles']
            print(f'          {info["cycles"]:>12,} cycles '
                  f'({info["cycles"]/x.shape[0]:7.1f}/window), '
                  f'stalls {info["in_stall"]}/{info["out_stall"]}, '
                  f'0 mismatches, {info["wall_seconds"]}s')
        info['name'], info['K'], info['COUT'] = L['name'], L['K'], L['COUT']
        info['windows'], info['nonzero_fraction'] = int(x.shape[0]), nz
        runs.append(info)

        nxt = requant(acc, np.asarray(L['requant']))
        q = nxt.reshape(b, h, w, L['COUT']).transpose(0, 3, 1, 2)
        if L['pool_after']:
            q = maxpool2(q)
        q = np.ascontiguousarray(q)

    pred = classify(q, manifest)
    acc_pct = float((pred == labels).mean())
    print(f'\nfinal feature map {q.shape}')
    print(f'accuracy on these {len(labels)} images: {acc_pct*100:.2f}%  '
          f'({int((pred == labels).sum())}/{len(labels)})')
    print(f'float model, full test set: {manifest["float_accuracy"]*100:.2f}%')

    report = dict(emulated=bool(args.emulate), images=len(labels), mode_seq=args.mode,
                  correct=int((pred == labels).sum()), accuracy=acc_pct,
                  float_accuracy=manifest['float_accuracy'],
                  predictions=pred.tolist(), labels=labels.tolist(), layers=runs)
    if not args.emulate:
        report['total_cycles'] = total_cycles
        report['cycles_per_image'] = total_cycles/len(labels)
        print(f'total {total_cycles:,} cycles for {len(labels)} images '
              f'= {total_cycles/len(labels):,.0f} cycles/image')
    (args.out/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(f'\nwritten to {args.out/"report.json"}')
    if args.emulate:
        print('EMULATED: this says the host pipeline is consistent. It says '
              'nothing about the hardware.')


if __name__ == '__main__':
    sys.exit(main())
