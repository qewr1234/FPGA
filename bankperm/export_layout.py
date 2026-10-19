"""Write a function-preserving copy of an integer export with a static tap order per layer.

    python bankperm/export_layout.py --layout skew --model dn_d10_c32_us_fx_qat --out build/layout_exports/skew
    python bankperm/export_layout.py --layout skew --orders ORDERS.json --model ... --out DIR   # L3, see below

The host builds every window (scripts/run_cifar.im2col, tap t = s*C + p: s the
3x3 position, p the channel) and sends the layer's weights with it, so the same
permutation of a layer's K taps, applied to its windows and to its weight
columns, leaves every accumulator unchanged (bankperm/skew_count.py: X' W'^T =
X W^T, and no partial sum can leave INT32). The skew (bankperm/PROTOCOL_2.md, L2)
puts channel p of position s in slot s*C + (p + s) % C, so its bank is
(s + p) % 4: skew_count.skew_order, new slot -> old tap index.

Which layers: the inputs of conv2..conv(L-1) that read one map with C % 4 == 0,
the rule of PROTOCOL_2.md and skew_count.py (for C % 4 == 1 the conventional
layout already has the skewed banks, and the first and last layers never
change). For dn_d10_c32_us_fx_qat that is conv2..conv9.

What is written to --out (the export directory itself, the folder
scripts/run_denoise.py --export-dir takes):

  <layer>_config.bin   for a skewed layer the weight columns in the new order,
                       w'[:, j] = w[:, tap_order[j]], bias unchanged; every other
                       config.bin byte for byte the source's
  manifest.json        the source's, with 'tap_order' (old tap index for each new
                       slot) appended to each skewed layer's entry. Written in the
                       exporter's own format (json.dumps, indent 2, LF, no trailing
                       newline unless the source has one): before writing, the source
                       re-serialized this way must give back its own bytes (CRLF read
                       as LF), so the added entries are the only bytes that differ. scripts/run_denoise.py puts a
                       layer's window columns in this order when it has one.
  int_eval.json, ...   every other file copied byte for byte
  layout_manifest.json the layout, the rule, the orders, and the sha256 of every
                       file written and of every source file

--orders ORDERS.json is for L3 (skew + relabeling, PROTOCOL_2.md): channel orders
in the format of bankperm/perms.json networks.<label>.orders or a GPT export's
permutation_manifest.json ({"orders": {producer: [original channel at each
position]}}; a perms.json-like file with "networks" is searched for the entry of
--model). They are first folded into the export with bankperm/fold.fold (producer
rows, consumer columns, per-channel lists), and the skew is then applied on top
of the folded export, so a relabeled channel's bank is (s + its new position) % 4,
the skewed rule the L3 fit optimizes. "Every other byte identical" then holds
against the folded export, not the original. Not yet used for a board run.

Nothing here runs on the board.
"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from skew_count import skew_order  # noqa: E402

LAYOUTS = ('skew',)
RULE = ('skew (bankperm/PROTOCOL_2.md L2): channel p of position s goes to slot s*C + (p + s) % C, bank (s + p) % 4; '
        'applied to the inputs of conv2..conv(L-1) that read one map with C % 4 == 0')
SEMANTICS = ('tap_order[j] = the old tap index (s*C + p) now in slot j: windows x\' = x[:, tap_order] '
             '(scripts/run_denoise.py), weights w\' = w[:, tap_order] in config.bin, bias unchanged')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(p):
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def manifest_bytes(obj):
    """The exporter's format: json.dumps(indent=2), no trailing newline, LF on every platform."""
    return json.dumps(obj, indent=2).encode('utf-8')


def skewed_layers(layers):
    """{name: tap_order} for the layers PROTOCOL_2.md skews (the rule of skew_count.run)."""
    out = {}
    for i, L in enumerate(layers):
        c = L['K'] // (L['kh']*L['kw'])
        if 0 < i < len(layers)-1 and len(L['inputs']) == 1 and c % 4 == 0 and c*L['kh']*L['kw'] == L['K']:
            out[L['name']] = skew_order(L['K'], c)
    return out


def read_orders(path, model):
    """Channel orders {producer: [original channel at each position]} from an orders JSON."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if 'networks' in data:
        hits = [v for v in data['networks'].values() if v.get('model') == model]
        if len(hits) != 1:
            raise SystemExit(f'{path}: {len(hits)} networks have model {model}; expected exactly one')
        data = hits[0]
    orders = data.get('orders', data)
    if not isinstance(orders, dict) or not all(isinstance(v, list) for v in orders.values()):
        raise SystemExit(f'{path}: no {{producer: [channel order]}} mapping found')
    return orders


def write_layout(src, dest, layout='skew', orders=None, orders_path=None):
    """Write the layout export of src to dest. -> the layout_manifest dict (also written to dest)."""
    if layout not in LAYOUTS:
        raise SystemExit(f'unknown layout {layout}; known: {", ".join(LAYOUTS)}')
    src, dest = Path(src).resolve(), Path(dest).resolve()
    if dest == src:
        raise SystemExit('--out is the source export; write the layout somewhere else')
    source_files = {p.name: sha256(p) for p in sorted(src.iterdir()) if p.is_file()}
    tmp = None
    base = src
    if orders:
        # L3: relabel first (bankperm/fold.py), then skew the folded export.
        try:
            src.relative_to(ROOT)                  # fold.fold records the source relative to the repository
        except ValueError:
            raise SystemExit(f'--orders needs a source export inside the repository ({ROOT}); {src} is not')
        import fold  # noqa: E402 (heavy imports only when relabeling)
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)/'folded'
        fold.fold(src, orders, base)
    try:
        raw_bytes = (base/'manifest.json').read_bytes().replace(b'\r\n', b'\n')
        raw = json.loads(raw_bytes)
        # Only the added entries may differ, so the source must round-trip exactly
        # (fold.py's manifests end in a newline, the exporter's do not: kept as found).
        tail = b'\n' if raw_bytes.endswith(b'\n') else b''
        if manifest_bytes(raw) + tail != raw_bytes:
            raise SystemExit(f'{base/"manifest.json"} is not in the json.dumps(indent=2) format; '
                             f'refusing to rewrite it')
        if any('tap_order' in node for node in raw['layers']):
            raise SystemExit(f'{base} already has a tap order; start from an export without one')
        man, layers = run_denoise.load_layers(base)
        taps = skewed_layers(layers)
        dest.mkdir(parents=True, exist_ok=True)
        stale = sorted(p.name for p in dest.iterdir()
                       if p.is_file() and p.name not in {q.name for q in base.iterdir()} | {'layout_manifest.json'})
        if stale or any(p.is_dir() for p in dest.iterdir()):
            raise SystemExit(f'{dest} holds files that are not part of this export ({stale or "subfolders"}); '
                             f'delete the folder and run again')
        changed = []
        for node, L in zip(raw['layers'], layers):
            assert node['name'] == L['name']
            if L['name'] not in taps:
                continue
            o = taps[L['name']]
            # The source's own INT32 words, columns moved, nothing re-quantized.
            blob = np.frombuffer((base/node['config']).read_bytes(), '<i4')
            k, cout = L['K'], L['COUT']
            if blob.size != cout*k + cout:
                raise SystemExit(f'{node["config"]}: {blob.size} words, expected {cout*k + cout}')
            words = np.concatenate([blob[:cout*k].reshape(cout, k)[:, o].reshape(-1), blob[cout*k:]])
            (dest/node['config']).write_bytes(words.astype('<i4').tobytes())
            node['tap_order'] = [int(v) for v in o]
            changed.append(node['config'])
        for p in sorted(base.iterdir()):
            if p.is_file() and p.name not in changed and p.name != 'manifest.json':
                shutil.copyfile(p, dest/p.name)
        (dest/'manifest.json').write_bytes(manifest_bytes(raw) + tail)
        files = {p.name: sha256(p) for p in sorted(dest.iterdir()) if p.is_file() and p.name != 'layout_manifest.json'}
        lm = dict(layout=layout + ('+relabeling' if orders else ''), model=man['model'], derived_from=rel(src),
                  written_by='bankperm/export_layout.py', rule=RULE, tap_order_semantics=SEMANTICS,
                  relabeling=None if not orders else dict(source=rel(orders_path) if orders_path else None,
                                                         folded_with='bankperm/fold.fold', orders=orders),
                  layers_reordered=list(taps), changed_files=sorted(changed + ['manifest.json']),
                  unchanged_files=sorted(n for n in files if n not in changed and n != 'manifest.json'),
                  tap_orders={k: [int(v) for v in o] for k, o in taps.items()},
                  files=files, source_files=source_files,
                  status='CPU export by bankperm/export_layout.py; checked by bankperm/check_skew_export.py')
        (dest/'layout_manifest.json').write_bytes(json.dumps(lm, indent=1).encode('utf-8') + b'\n')
        return lm
    finally:
        if tmp:
            tmp.cleanup()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--layout', default='skew', choices=LAYOUTS)
    ap.add_argument('--model', required=True, help='denoise/export/<model>/ is the source')
    ap.add_argument('--src', type=Path, help='another source export directory (default denoise/export/<model>)')
    ap.add_argument('--orders', type=Path, help='channel orders to fold in first (L3, skew + relabeling)')
    ap.add_argument('--out', type=Path, required=True, help='the new export directory')
    args = ap.parse_args()
    src = args.src or ROOT/'denoise'/'export'/args.model
    if not (src/'manifest.json').is_file():
        raise SystemExit(f'missing export manifest: {src}')
    if json.loads((src/'manifest.json').read_text(encoding='utf-8')).get('model') != args.model:
        raise SystemExit(f'--model {args.model} disagrees with the manifest at {src}')
    orders = read_orders(args.orders, args.model) if args.orders else None
    lm = write_layout(src, args.out, args.layout, orders, args.orders)
    print(f'{lm["layout"]} export of {lm["model"]} -> {args.out}')
    print(f'  tap order on {", ".join(lm["layers_reordered"]) or "no layer"}; '
          f'changed {", ".join(lm["changed_files"])}; {len(lm["unchanged_files"])} file(s) copied unchanged')


if __name__ == '__main__':
    main()
