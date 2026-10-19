"""Fold each network's fitted permutation into its weights and check it is the same function.

    python bankperm/fold.py [--out DIR] [--jobs 2]   # writes bankperm/fold_check.json (about 5 minutes)

The permutation of bankperm/perms.json (`orders`, keyed by the producer: position
-> original channel of the producer's output map) is folded into a re-exported
network, in the export format of scripts/q1_reviewer_export.py (config bins of
INT32 words: weights in tap order (ky, kx, channel), then bias; manifest.json
with the per-channel lists reordered):

  * producer: its output channels -- weight rows, bias, requant and w_scale --
    in the new order; for a maxout or averaging layer, which computes 2C maps and
    keeps channel c as max (or mean) of maps c and c+C (run_denoise.denoise), both
    maps c and c+C of each pooled channel move with it;
  * consumer: its input taps, s*C_in + p reading original channel order[p].

The fold is generic (graph and chain manifests, ReLU, maxout and averaging). Where
q1_reviewer_export.export_network applies (graph, plain ReLU) its export is made
too and must be byte-identical. For B-32 ReLU s1 the published Frozen groups
(research/q1_codesign/bank_export_perm.json) are also folded and compared with
the Frozen ZIP's config bins byte for byte.

Each permuted export (the export directory, read back with
run_denoise.load_layers) and the original are then emulated with run_denoise.denoise
on Set12 05.png and BSD68 test001.png (sigma of the network, test_noise seed 0):
the denoised arrays and PNG bytes must be identical, every layer's windows must be
the original's with the input columns permuted (the claim evaluate.py counts
with), and every layer's INT32 accumulators the original's with the output
columns permuted. --cli also runs scripts/run_denoise.py --export-dir --emulate on
each permuted export and compares its PNG with the original's.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from common import psnr  # noqa: E402
from count_test_sets import MODELS  # noqa: E402
from fit import FROZEN_ZIP, H0_LABEL, PUBLISHED, emulate, export_dir, noisy_input, write_json  # noqa: E402
from q1_reviewer_export import export_network  # noqa: E402

IMAGES = [('Set12', '05.png'), ('BSD68', 'test001.png')]
POOLED = ('maxout', 'avg')


def map_channels(name, by_name, man):
    """Channels of the map a node reads from `name` (pooled maps have half the outputs)."""
    if name == 'image':
        return int(man['img_ch'])
    L = by_name[name]
    return L['COUT']//2 if L['post'] in POOLED else L['COUT']


def output_order(L, order):
    """The producer's output columns for a map permutation: c and c+C together when pooled."""
    order = np.asarray(order, np.int64)
    if L['post'] in POOLED:
        c = L['COUT']//2
        assert len(order) == c and sorted(order) == list(range(c)), L['name']
        return np.concatenate([order, order + c])
    if L['post'] != 'none':
        raise SystemExit(f'{L["name"]}: no fold for post-op {L["post"]}')
    assert len(order) == L['COUT'] and sorted(order) == list(range(L['COUT'])), L['name']
    return order


def input_order(L, orders, by_name, man):
    """Original input channel read at each position of L's concatenated input."""
    idx, off = [], 0
    for parent in L['inputs']:
        ch = map_channels(parent, by_name, man)
        idx.extend(off + np.asarray(orders.get(parent, range(ch)), np.int64))
        off += ch
    assert off*L['kh']*L['kw'] == L['K'], L['name']
    return np.asarray(idx, np.int64)


def fold(src, orders, dest):
    """Write the permuted export of src to dest. -> per-layer (input order, output columns)."""
    raw = json.loads((src/'manifest.json').read_text())
    if any('tap_order' in node for node in raw['layers']):
        # A layout export (bankperm/export_layout.py) keeps weight columns in another tap
        # order; the fold below assumes (ky, kx, channel) and would write another function.
        raise SystemExit(f'{src} has a tap order (a layout export): fold the export without one, then apply the '
                         f'layout on top (bankperm/export_layout.py --orders)')
    man, layers = run_denoise.load_layers(src)
    by_name = {L['name']: L for L in layers}
    if layers[-1]['name'] in orders or 'image' in orders:
        raise SystemExit('the image and the last layer output are never permuted')
    dest.mkdir(parents=True, exist_ok=True)
    perm = {}
    for node, L in zip(raw['layers'], layers):
        assert node['name'] == L['name']
        taps, cout = L['kh']*L['kw'], L['COUT']
        src_idx = input_order(L, orders, by_name, man)
        pout = output_order(L, orders[L['name']]) if L['name'] in orders else np.arange(cout)
        w = L['wq'].reshape(cout, taps, len(src_idx))[pout][:, :, src_idx].reshape(cout, L['K'])
        words = np.concatenate([w.astype('<i4').reshape(-1), L['bq'][pout].astype('<i4')])
        (dest/node['config']).write_bytes(words.tobytes())
        for key in ('requant', 'w_scale', 'a_scale_out'):
            vals = node.get(key)
            if isinstance(vals, list):
                if len(vals) != cout:
                    raise SystemExit(f'{L["name"]}: {key} has {len(vals)} entries for {cout} outputs')
                node[key] = [vals[i] for i in pout]
        perm[L['name']] = (src_idx, pout)
    (dest/'manifest.json').write_text(json.dumps(raw, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    shutil.copy2(src/'int_eval.json', dest/'int_eval.json')
    (dest/'permutation_manifest.json').write_text(json.dumps(dict(
        derived_from=str(src.relative_to(ROOT)), orders=orders,
        status='CPU export by bankperm/fold.py; not run on the FPGA'), indent=2) + '\n')
    return perm


def window_columns(src_idx, taps):
    return (np.arange(taps)[:, None]*len(src_idx) + src_idx[None, :]).reshape(-1)


def png_bytes(out):
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format='PNG')
    return buf.getvalue()


def compare(model, perm, dest, cli):
    """Emulate original and permuted export on IMAGES; compare outputs, windows, accumulators."""
    src = export_dir(model)
    man0, lay0 = run_denoise.load_layers(src)
    man1, lay1 = run_denoise.load_layers(dest)
    rows = []
    for set_name, image in IMAGES:
        q_in, clean = noisy_input(set_name, image, man0['sigma'])
        ref = {}
        out0 = emulate(man0, lay0, q_in, lambda L, x, acc: ref.__setitem__(L['name'], (x.copy(), acc.copy())))
        win_ok, acc_ok = {}, {}

        def check(L, x, acc):
            x0, a0 = ref[L['name']]
            src_idx, pout = perm[L['name']]
            win_ok[L['name']] = bool(np.array_equal(x, x0[:, window_columns(src_idx, L['kh']*L['kw'])]))
            acc_ok[L['name']] = bool(np.array_equal(acc, a0[:, pout]))

        out1 = emulate(man1, lay1, q_in, check)
        del ref
        p0, p1 = png_bytes(out0), png_bytes(out1)
        ie = json.loads((src/'int_eval.json').read_text())[set_name]['per_image'][image]
        ps = [float(psnr(clean, o.astype(np.float32)/255)) for o in (out0, out1)]
        row = dict(set=set_name, image=image, output_identical=bool(np.array_equal(out0, out1)),
                   png_identical=p0 == p1, png_sha256=hashlib.sha256(p1).hexdigest(),
                   psnr_original=ps[0], psnr_permuted=ps[1], psnr_int_eval=ie,
                   psnr_matches_int_eval=all(abs(p - ie) <= 1e-5 for p in ps),
                   windows_are_column_permutation=all(win_ok.values()),
                   accumulators_are_column_permutation=all(acc_ok.values()),
                   layers_checked=len(acc_ok), layers_with_input_permuted=sum(
                       not np.array_equal(perm[n][0], np.arange(len(perm[n][0]))) for n in acc_ok),
                   layers_with_output_permuted=sum(
                       not np.array_equal(perm[n][1], np.arange(len(perm[n][1]))) for n in acc_ok))
        if not all(win_ok.values()) or not all(acc_ok.values()):
            row['failing_layers'] = sorted(n for n in acc_ok if not (win_ok[n] and acc_ok[n]))
        if cli:
            out_dir = dest.parent/f'cli_{model}_{Path(image).stem}'
            r = subprocess.run([sys.executable, str(ROOT/'scripts'/'run_denoise.py'), '--model', model,
                                '--export-dir', str(dest), '--emulate', '--set', set_name, '--images', image,
                                '--out', str(out_dir)], capture_output=True, text=True)
            png = out_dir/f'{Path(image).stem}_denoised.png'
            row['cli'] = dict(exit_code=r.returncode, png_identical=png.exists() and png.read_bytes() == p0)
        rows.append(row)
    return rows


def reference_export(model, orders, dest):
    """q1_reviewer_export.export_network on the same orders, where it applies (graph, ReLU)."""
    man, layers = run_denoise.load_layers(export_dir(model))
    if not man.get('graph') or any(L['post'] != 'none' for L in layers):
        return dict(applies=False, why='q1_reviewer_export supports graph manifests with plain ReLU only')
    by_name = {L['name']: L for L in layers}
    consumer = {L['inputs'][0]: L['name'] for L in layers if len(L['inputs']) == 1}
    report = dict(model=model, layers=[dict(layer=consumer[p], original_channel_order=o) for p, o in orders.items()])
    ref = dest.parent/f'ref_{model}'
    ref.mkdir(parents=True, exist_ok=True)
    export_network(export_dir(model), report, ref)
    same = {n: (ref/n).read_bytes() == (dest/n).read_bytes()
            for n in ['manifest.json'] + [by_name[L['name']]['config'] for L in layers]}
    return dict(applies=True, files_compared=len(same), byte_identical=all(same.values()),
                differing=sorted(n for n, v in same.items() if not v))


def frozen_check(dest):
    """Fold the published Frozen groups; compare with the Frozen ZIP byte for byte."""
    pub = json.loads(PUBLISHED.read_text())
    model = pub['model']
    out = dest/'frozen'/model
    fold(export_dir(model), pub['orders'], out)
    rows, ok = {}, True
    with zipfile.ZipFile(FROZEN_ZIP) as z:
        names = [n for n in z.namelist() if n.startswith(model + '/') and n.endswith('_config.bin')]
        for n in sorted(names):
            same = z.read(n) == (out/Path(n).name).read_bytes()
            rows[Path(n).name] = same
            ok &= same
        zman = z.read(f'{model}/manifest.json')
        zeval = z.read(f'{model}/int_eval.json')
    mine = (out/'manifest.json').read_bytes()
    return dict(zip=str(FROZEN_ZIP.relative_to(ROOT)), published=str(PUBLISHED.relative_to(ROOT)),
                config_bins_compared=len(rows), config_bins_byte_identical=ok,
                differing_config_bins=sorted(n for n, v in rows.items() if not v),
                manifest_same_content=json.loads(zman) == json.loads(mine), manifest_byte_identical=zman == mine,
                int_eval_byte_identical=zeval == (out/'int_eval.json').read_bytes())


def image_ok(r):
    cli = r.get('cli', dict(exit_code=0, png_identical=True))
    return (r['output_identical'] and r['png_identical'] and r['psnr_matches_int_eval']
            and r['windows_are_column_permutation'] and r['accumulators_are_column_permutation']
            and cli['exit_code'] == 0 and cli['png_identical'])


def run(label, model, orders, dest, cli):
    t0 = time.time()
    perm = fold(export_dir(model), orders, dest)
    rec = dict(model=model, q1_reviewer_export_reference=reference_export(model, orders, dest),
               images=compare(model, perm, dest, cli))
    rec['all_ok'] = all(map(image_ok, rec['images'])) and rec['q1_reviewer_export_reference'].get('byte_identical', True)
    rec['seconds'] = round(time.time() - t0, 1)
    return label, rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, help='keep the permuted exports here (default: a temporary directory)')
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--cli', action='store_true', help='also run scripts/run_denoise.py on each permuted export')
    args = ap.parse_args()
    perms = json.loads((HERE/'perms.json').read_text())['networks']
    tmp = None if args.out else tempfile.TemporaryDirectory()
    base = args.out or Path(tmp.name)
    base.mkdir(parents=True, exist_ok=True)
    res = dict(images=[f'{s} {i}' for s, i in IMAGES], noise='sigma of the network, test_noise seed 0',
               orders='bankperm/perms.json networks.<label>.orders', networks={})
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(run, label, p['model'], p['orders'], base/'perm'/p['model'], args.cli)
                for label, p in perms.items()]
        for fut in concurrent.futures.as_completed(futs):
            label, rec = fut.result()
            res['networks'][label] = rec
            print(f'{label:<26} all ok {rec["all_ok"]}   ' + '  '.join(
                f'{r["image"]}: out {r["output_identical"]} png {r["png_identical"]} '
                f'win {r["windows_are_column_permutation"]} acc {r["accumulators_are_column_permutation"]}'
                for r in rec['images']) + f'   ref {rec["q1_reviewer_export_reference"].get("byte_identical", "n/a")}'
                f'   ({rec["seconds"]} s)', flush=True)
    res['networks'] = {k: res['networks'][k] for k in perms}
    res['frozen_zip'] = frozen_check(base)
    res['frozen_zip']['network'] = H0_LABEL
    print('Frozen ZIP:', res['frozen_zip'])
    res['all_ok'] = all(r['all_ok'] for r in res['networks'].values()) and res['frozen_zip']['config_bins_byte_identical']
    write_json(HERE/'fold_check.json', res)
    print('wrote', HERE/'fold_check.json')
    if tmp:
        tmp.cleanup()


if __name__ == '__main__':
    main()
