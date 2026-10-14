"""One table of every exported denoiser: board cost against integer PSNR.

    python denoise/results_table.py                 # every denoise/export/*
    python denoise/results_table.py dn_d7_c32 dn_d10_c64_us_es ...

Reads each export's manifest.json and int_eval.json, so every number is the
one the quantizer measured (integer = what the board computes). Cycles per
pixel are the cycle model with the measured corrections, recomputed from the
manifest's layers (train_denoise.board_cycles_per_pixel_measured) so old and
new exports are on the same footing, and the board's own count per pixel
where a board_runs/<model>_05.json exists; parameters are the INT8 weights
the board loads. The last columns count the images on which the integer
model beats BM3D re-measured under the same clipped 7-bit input
(denoise/baselines.json).
"""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from train_denoise import board_cycles_per_pixel_measured  # noqa: E402


def model_cycles(man):
    """Cycles per pixel from the corrected model; legacy manifests carry no wpp per layer."""
    wpp_default = 0.25 if man.get('unshuffle') else 1.0
    return board_cycles_per_pixel_measured([(None, L['K'], L['COUT'], L.get('wpp', wpp_default)) for L in man['layers']])


def board_cycles(name):
    """The board's own cycles per pixel on Set12 05.png, if that run was recorded."""
    f = HERE/'board_runs'/f'{name}_05.json'
    if not f.exists():
        return None
    im = json.loads(f.read_text())['images'][0]
    return im['cycles']/(im['width']*im['height'])


def row(export, bm3d):
    man = json.loads((export/'manifest.json').read_text())
    ev = json.loads((export/'int_eval.json').read_text())
    params = sum(L['K']*L['COUT'] + L['COUT'] for L in man['layers'])
    wins = {}
    for s in ('Set12', 'BSD68'):
        d = [ev[s]['per_image'][k] - bm3d[s][k] for k in ev[s]['per_image']]
        wins[s] = f'{sum(v > 0 for v in d)}/{len(d)}'
    tags = []
    if man.get('unet'):
        tags.append('unet')
    if man.get('maxout'):
        tags.append('maxout')
    if any(L.get('post') == 'avg' for L in man['layers']):
        tags.append('avg')
    if man.get('qat'):
        tags.append('qat')
    if any(L.get('dilation', 1) > 1 for L in man['layers']):
        tags.append('dil')
    return dict(name=man['model'], cycles=model_cycles(man), board=board_cycles(man['model']),
                params=params,
                tags=' '.join(tags), set12_f=ev['Set12']['float'], set12_i=ev['Set12']['integer'],
                bsd_f=ev['BSD68']['float'], bsd_i=ev['BSD68']['integer'],
                w12=wins['Set12'], w68=wins['BSD68'])


def main():
    bm = json.loads((HERE/'baselines.json').read_text())['sets']
    bm3d = {s: bm[s]['bm3d']['per_image'] for s in ('Set12', 'BSD68')}
    names = sys.argv[1:] or sorted(p.name for p in (HERE/'export').iterdir()
                                   if (p/'int_eval.json').exists() and not p.name.startswith('_'))
    rows = [row(HERE/'export'/n, bm3d) for n in names]
    rows.sort(key=lambda r: (r['cycles'], -r['set12_i']))
    print(f'BM3D (same clipped 7-bit input): Set12 {bm["Set12"]["bm3d"]["mean"]:.2f}  '
          f'BSD68 {bm["BSD68"]["bm3d"]["mean"]:.2f}\n')
    print('| model | cycles/px model (board) | INT8 params | | Set12 float / int | BSD68 float / int | int loss '
          '| > BM3D Set12 | > BM3D BSD68 |')
    print('|---|---:|---:|---|---|---|---|---|---|')
    for r in rows:
        cyc = f'{r["cycles"]:,.0f}' + (f' ({r["board"]:,.0f})' if r['board'] else '')
        print(f'| {r["name"]} | {cyc} | {r["params"]/1e3:.0f}k | {r["tags"]} '
              f'| {r["set12_f"]:.2f} / **{r["set12_i"]:.2f}** | {r["bsd_f"]:.2f} / **{r["bsd_i"]:.2f}** '
              f'| {r["set12_i"]-r["set12_f"]:+.2f} / {r["bsd_i"]-r["bsd_f"]:+.2f} '
              f'| {r["w12"]} | {r["w68"]} |')


if __name__ == '__main__':
    main()
