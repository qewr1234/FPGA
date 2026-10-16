"""Denoise images on the board: noisy picture in, clean picture out.

    python scripts/run_denoise.py --emulate                       # host only
    python scripts/run_denoise.py --xsdb C:/Vivado/2026.1/Vivado/bin/xsdb.bat \
                                  --images 01.png,05.png

Same bitstream as the CIFAR run (K=1152, COUT=128, P=16, T=4, runtime geometry)
and the same board path: every layer is im2col on the host, then one or more
board runs of scripts/run_board_xsdb.tcl through run_cifar.run_board, which
also checks every output word against the host oracle on the board side.

What is new here is size. A 256x256 image is 65,536 windows per layer -- 19 MB
of input for a 32-channel layer, where a CIFAR layer was 1,024 windows per image.
A 512x512 image is 75 MB per layer, past the AXI DMA's 64 MB transfer limit
(c_sg_length_width 26) and, four buffers of it, past the ZedBoard's 512 MB. So a
layer is split into tiles of --tile windows, each its own board run. Windows are
independent of each other, so the tiling changes nothing in the result.

The noisy input is common.test_noise with seed 0 -- the very images the
quantizer and the baselines were scored on -- so a board PSNR is directly
comparable with denoise/export/<model>/int_eval.json, and is checked against it.

Writes build/denoise_run/<image>_{clean,noisy,denoised}.png and report.json.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'denoise'))
import run_cifar  # noqa: E402
from run_cifar import board_results, im2col, oracle, requant, run_board, write_board_files  # noqa: E402
from common import (QMAX_A, load_set, pad_mult, psnr, shuffle2, shuffle2c, test_noise, to_image,  # noqa: E402
                    unshuffle2)


def load_layers(export):
    """The manifest and its layers (nodes), with their integer weights.

    A manifest written before the graph form is a chain: every layer reads the
    one before it (the last also the image when skip), 3x3, stride 1, and a
    maxout model keeps the larger of each pair after every hidden layer."""
    man = json.loads((export/'manifest.json').read_text())
    n = len(man['layers'])
    if not man.get('graph'):
        unsh = man.get('unshuffle', False)
        man['pad_to'], man['img_ch'] = (2, 4) if unsh else (1, 1)
        for i, L in enumerate(man['layers']):
            L['inputs'] = ([f'conv{i}'] if i else ['image']) + (
                ['image'] if i == n-1 and man['input_channel_appended_to_last_layer'] else [])
            L.update(kh=3, kw=3, stride=1, dilation=L.get('dilation', 1), wpp=0.25 if unsh else 1.0,
                     post='maxout' if man.get('maxout') and i < n-1 else 'none')
    out = []
    for L in man['layers']:
        blob = np.frombuffer((export/L['config']).read_bytes(), '<i4')
        k, c = L['K'], L['COUT']
        out.append(dict(L, wq=blob[:c*k].reshape(c, k).astype(np.int8),
                        bq=blob[c*k:].astype(np.int32), cfg=export/L['config']))
    return man, out


def node_geometry(L, h, w):
    """Padding and output size of node L on an h x w map."""
    pad = L['dilation']*(L['kh']//2) if L['kh'] % 2 else 0
    d, s = L['dilation'], L['stride']
    return pad, (h + 2*pad - d*(L['kh']-1) - 1)//s + 1, (w + 2*pad - d*(L['kw']-1) - 1)//s + 1


def run_layer(L, x, args, tag):
    """All windows of one layer: emulated, or on the board in tiles. -> (N, COUT) INT32."""
    gold = oracle(x, L['wq'], L['bq'])
    if args.emulate:
        return gold, dict(emulated=True, runs=0, mismatches=0)
    n, k = x.shape
    acc = np.empty_like(gold)
    cycles = wall = 0
    clocks = set()
    runs = 0
    for s in range(0, n, args.tile):
        e = min(n, s+args.tile)
        xt, gt = x[s:e], gold[s:e]
        # Whole 32-bit beats: pad with zero windows, whose outputs are dropped.
        pad = 0
        while ((e-s+pad)*k) % 4:
            pad += 1
        if pad:
            xt = np.concatenate([xt, np.zeros((pad, k), xt.dtype)])
            gt = np.concatenate([gt, oracle(xt[-pad:], L['wq'], L['bq'])])
        write_board_files(L['cfg'], xt, gt, args.mode)
        info = run_board(args.xsdb, args.build, args.out/f'{tag}_{L["name"]}_t{s}_xsdb.log',
                         args.fclk)
        res = board_results(xt.shape[0], L['COUT'])
        acc[s:e] = res[:e-s]
        cycles += info['cycles']; wall += info['wall_seconds']; runs += 1
        if info.get('fclk_mhz'):
            clocks.add(round(info['fclk_mhz'], 2))
    if not np.array_equal(acc, gold):
        raise SystemExit(f'{tag} {L["name"]}: board results differ from the oracle')
    return acc, dict(emulated=False, runs=runs, cycles=int(cycles), wall_seconds=round(wall, 1),
                     mismatches=0, fclk_mhz=sorted(clocks))


def denoise(q_in, man, layers, args, tag, start=1):
    """7-bit noisy image (H, W) -> 8-bit denoised image, per-layer records.

    The maps a node may still read are saved to <out>/<tag>_maps<N>.npz before
    node N runs, so a node that fails on the board can be retried alone
    (start=N) instead of paying for every node before it again.
    """
    H, W = q_in.shape
    unshuffled = man.get('unshuffle', False)
    # An unshuffled model runs on the four 2x2 phases of the padded image.
    img = pad_mult(q_in, man.get('pad_to', 2 if unshuffled else 1))
    base = (unshuffle2(img) if unshuffled else img[None]).astype(np.uint8)
    maps = {'image': base}                                # name -> (C, h, w) codes
    save = getattr(args, 'out', None)
    if start > 1:
        src = args.out/f'{tag}_maps{start}.npz'
        if not src.exists():
            raise SystemExit(f'{src} is not there, so layer {start} has nothing to resume '
                             f'from. Run from layer 1.')
        maps = dict(np.load(src))
        print(f'  resuming at {layers[start-1]["name"]} from {src}')
    recs = []
    for i, L in enumerate(layers):
        if i+1 < start:
            continue
        if save is not None and not args.emulate:
            np.savez(args.out/f'{tag}_maps{i+1}.npz', **maps)
        q = np.concatenate([maps[k] for k in L['inputs']], 0)
        pad, oh, ow = node_geometry(L, *q.shape[1:])
        # The window's shape (dilation, stride, kernel) is the host's business;
        # the core sees K values.
        x = im2col(q[None], kh=L['kh'], kw=L['kw'], pad=pad, dilation=L['dilation'], stride=L['stride'])
        if x.shape[1] != L['K']:
            raise SystemExit(f'{L["name"]}: windows are {x.shape[1]} taps, weights {L["K"]}')
        t0 = time.time()
        try:
            acc, info = run_layer(L, x, args, tag)
        except SystemExit as e:
            raise SystemExit(f'{e}\n\nRetry from this layer with\n'
                             f'  --images {tag}.png --start-layer {i+1}\n'
                             f'which reads {args.out}/{tag}_maps{i+1}.npz and skips the '
                             f'{i} layer(s) that already passed.')
        info.update(name=L['name'], K=L['K'], COUT=L['COUT'], windows=int(x.shape[0]),
                    nonzero_fraction=float((x != 0).mean()), host_seconds=round(time.time()-t0, 1))
        recs.append(info)
        msg = f'  {L["name"]}: {x.shape[0]:>7} windows x K={L["K"]:>4} -> COUT={L["COUT"]:>3}'
        if not info['emulated']:
            msg += (f'   {info["cycles"]:>12,} cycles ({info["cycles"]/x.shape[0]:.1f}/window) '
                    f'in {info["runs"]} run(s), 0 mismatches')
        print(msg, flush=True)
        if i < len(layers)-1:
            r = requant(acc, np.asarray(L['requant'])).reshape(oh, ow, L['COUT']).transpose(2, 0, 1)
            if L['post'] == 'maxout':
                # The core computed 2C maps; channel c goes on as the larger of
                # maps c and c+C (after requantization, which is monotonic).
                c = L['COUT']//2
                r = np.maximum(r[:c], r[c:])
            elif L['post'] == 'avg':
                # The maxout control: the mean of each pair, rounded half up.
                c = L['COUT']//2
                r = ((r[:c].astype(np.int64) + r[c:].astype(np.int64) + 1) >> 1).astype(r.dtype)
            elif L['post'] == 'shuffle2':
                r = shuffle2c(r)                  # 4C codes placed one level up
            maps[L['name']] = np.ascontiguousarray(r)
        else:
            # (N, COUT) -> (COUT, oh, ow), then the same host arithmetic the
            # quantizer scored: one clean channel, or the residual sign pair.
            acc_maps = acc.T.reshape(L['COUT'], oh, ow)
            if unshuffled:
                out = shuffle2(to_image(acc_maps, base, L['to_pixel'], False), H, W)
            else:
                out = to_image(acc_maps, q_in, L['to_pixel'], man.get('residual_output', False))
    return out, recs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default='dn_d7_c32', help='denoise/export/<model>/')
    ap.add_argument('--set', default='Set12', choices=['Set12', 'BSD68'])
    ap.add_argument('--images', help='comma separated file names (default: all of the set)')
    ap.add_argument('--emulate', action='store_true')
    ap.add_argument('--xsdb', type=Path)
    ap.add_argument('--build', type=Path)
    ap.add_argument('--fclk', type=float)
    ap.add_argument('--mode', type=int, default=1, choices=[0, 1])
    ap.add_argument('--tile', type=int, default=65536,
                    help='windows per board run (65536 = one 256x256 image)')
    ap.add_argument('--start-layer', type=int, default=1,
                    help='resume one image at this layer, from the input the failed run saved')
    ap.add_argument('--out', type=Path, default=ROOT/'build'/'denoise_run')
    ap.add_argument('--board-dir', type=Path, default=ROOT/'build'/'denoise_board')
    args = ap.parse_args()
    if not args.emulate and not args.xsdb:
        raise SystemExit('give --xsdb to run on the board, or --emulate for the host side alone')
    run_cifar.BOARD = args.board_dir.resolve()

    export = ROOT/'denoise'/'export'/args.model
    man, layers = load_layers(export)
    int_eval = json.loads((export/'int_eval.json').read_text())[args.set]['per_image']
    tests = test_noise(load_set(args.set), man['sigma'], seed=0)
    if args.images:
        want = args.images.split(',')
        tests = [t for t in tests if t[0] in want]
        missing = set(want) - {t[0] for t in tests}
        if missing:
            raise SystemExit(f'not in {args.set}: {sorted(missing)}')
    if args.start_layer > 1 and len(tests) != 1:
        raise SystemExit('--start-layer resumes one image: give exactly one with --images')
    args.out.mkdir(parents=True, exist_ok=True)
    print(f'{man["model"]}: {len(layers)} layers, {"emulating" if args.emulate else "on the board"}, '
          f'{len(tests)} image(s) of {args.set}, sigma {man["sigma"]}\n')

    rows = []
    for name, clean, noisy in tests:
        stem = Path(name).stem
        q_in = np.rint(noisy*QMAX_A).astype(np.uint8)
        print(f'{name} {clean.shape[1]}x{clean.shape[0]}')
        out, recs = denoise(q_in, man, layers, args, stem, args.start_layer)
        p_noisy, p_out = psnr(clean, noisy), psnr(clean, out.astype(np.float32)/255)
        # The quantizer scored this exact image with the same integer model.
        if abs(p_out - int_eval[name]) > 1e-6:
            raise SystemExit(f'{name}: {p_out:.4f} dB here but {int_eval[name]:.4f} dB in '
                             f'int_eval.json -- the driver and the quantizer disagree')
        Image.fromarray(np.uint8(np.rint(clean*255))).save(args.out/f'{stem}_clean.png')
        Image.fromarray(np.uint8(np.rint(noisy*255))).save(args.out/f'{stem}_noisy.png')
        Image.fromarray(out).save(args.out/f'{stem}_denoised.png')
        row = dict(image=name, width=clean.shape[1], height=clean.shape[0],
                   psnr_noisy=p_noisy, psnr_denoised=p_out, start_layer=args.start_layer,
                   layers=recs)
        if not args.emulate and args.start_layer == 1:
            row['cycles'] = sum(r['cycles'] for r in recs)
        rows.append(row)
        print(f'  PSNR {p_noisy:.2f} dB -> {p_out:.2f} dB   (matches int_eval.json)\n')

    report = dict(emulated=bool(args.emulate), model=man['model'], set=args.set, sigma=man['sigma'],
                  mode_seq=args.mode, images=rows,
                  mean_psnr_noisy=float(np.mean([r['psnr_noisy'] for r in rows])),
                  mean_psnr_denoised=float(np.mean([r['psnr_denoised'] for r in rows])),
                  mismatches=0)
    (args.out/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(f'mean PSNR {report["mean_psnr_noisy"]:.2f} -> {report["mean_psnr_denoised"]:.2f} dB '
          f'over {len(rows)} image(s) -> {args.out/"report.json"}')
    if args.emulate:
        print('EMULATED: the host pipeline is consistent. It says nothing about the hardware.')


if __name__ == '__main__':
    sys.exit(main())
