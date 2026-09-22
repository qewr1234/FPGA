"""How long the CIFAR-10 network takes, from the cycle model the board confirms.

Both cores cost, per window,

    max(K, GROUPS * per_group)          GROUPS = ceil(COUT / P)

where per_group is the taps one group issues: K on Channel in dense mode, the
nonzero count in sparse mode; ceil(K/T) on Bank in dense mode, the largest of
the T bank counts in sparse mode. The max is the window-level overlap: loading
the next window costs K cycles whatever the issue engine is doing, so once the
issue side is faster than the feed, the feed is what is left.

--validate replays that against every configuration measured on hardware and in
simulation. It reproduces all seven within 1.3 cycles per window, which is what
makes the projection below worth reading.

The projection itself is DENSE: every tap issued, no zero skipped. That is an
upper bound on cycles, not an estimate, and it needs no assumption about CIFAR
activations -- which do not exist yet, because the network is still training.
--sparsity applies a measured density instead, and says so.

Wall-clock is only given where Fmax was measured. Cycles are geometry.

    python scripts/cifar_budget.py --validate
    python scripts/cifar_budget.py
    python scripts/cifar_budget.py --sparsity 0.569     # the VGG probe's density
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The network cifar/train_cifar.py builds: (cin, cout) per convolution, 3x3,
# padding 1, 2x2 max pool after every second one, on a 32x32 input. Read from
# the export when it exists, so this follows the model rather than describing it.
PLANNED = [(3, 32), (32, 32), (32, 64), (64, 64), (64, 128), (128, 128)]

# Measured, from paper/figures/data.py. Cycles per window on the 512-frame
# evaluation probe, mode_seq 2 (dense and sparse windows alternating).
MEASURED = [
    ('Channel', 8, 1, 7230.6), ('Channel', 32, 1, 1808.1),
    ('Channel', 64, 1, 910.7), ('Channel', 128, 1, 577.3),
    ('Bank', 8, 4, 1910.7), ('Bank', 8, 8, 1019.6), ('Bank', 16, 4, 956.8),
]
# Routed WNS on a 10 ns constraint, for the two configurations that were built.
FMAX = {('Channel', 64, 1): 1000.0/(10-0.157), ('Bank', 16, 4): 1000.0/(10-1.040)}


def per_window(k, cout, p, t, per_group):
    """One window's cycles: issue, or the feed if the feed is slower."""
    groups = (cout+p-1)//p
    return max(k, groups*per_group)


def dense_per_group(k, t):
    return (k+t-1)//t


def layers_from(export):
    """The real layer shapes if they have been exported, else the planned ones."""
    mf = export/'manifest.json'
    if mf.exists():
        m = json.loads(mf.read_text())
        h = 32
        out = []
        for L in m['layers']:
            out.append((L['name'], h*h, L['K'], L['COUT']))
            if L['pool_after']:
                h //= 2
        return out, 'cifar/export/manifest.json'
    out, h = [], 32
    for i, (cin, cout) in enumerate(PLANNED):
        out.append((f'conv{i+1}', h*h, 9*cin, cout))
        if i % 2 == 1:
            h //= 2
    return out, 'the network train_cifar.py builds (not yet exported)'


def validate():
    """The model against every configuration that was actually run."""
    sys.path.insert(0, str(ROOT/'scripts'))
    from legacy_run_checks import read_probe
    x, w, _b, _ids, _y = read_probe(ROOT/'data'/'evaluation.wpr')
    k, cout = len(x[0]), len(w)
    print(f'evaluation probe: {len(x)} frames, K={k}, COUT={cout}, '
          f'mean nonzero {sum(sum(1 for v in r if v) for r in x)/len(x)/k:.3f}\n')
    print(f'{"core":<9}{"P":>4}{"T":>3}   {"model":>9}{"measured":>10}{"delta":>8}')
    worst = 0.0
    for name, p, t, meas in MEASURED:
        total = 0
        for i, row in enumerate(x):
            for sparse in (False, True):      # mode_seq 2 alternates
                if sparse:
                    counts = [0]*t
                    for j, v in enumerate(row):
                        if v:
                            counts[j % t] += 1
                    per = max(counts) if any(counts) else 1
                else:
                    per = dense_per_group(k, t)
                total += per_window(k, cout, p, t, per)
        model = total/(2*len(x))
        worst = max(worst, abs(model-meas))
        print(f'{name:<9}{p:>4}{t:>3}   {model:>9.1f}{meas:>10.1f}{model-meas:>+8.1f}')
    print(f'\nlargest disagreement: {worst:.1f} cycles per window, on windows '
          f'costing {min(m for *_, m in MEASURED):.0f} to '
          f'{max(m for *_, m in MEASURED):.0f}.')
    return worst


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--export', type=Path, default=ROOT/'cifar'/'export')
    ap.add_argument('--validate', action='store_true',
                    help='replay the model against the measured configurations')
    ap.add_argument('--sparsity', type=float,
                    help='fraction of activations that are nonzero. Omit for '
                         'dense, which is a bound rather than an assumption.')
    ap.add_argument('--imbalance', type=float, default=1.157,
                    help='bank load imbalance at T=4, measured on the VGG probe')
    args = ap.parse_args()

    if args.validate:
        validate()
        return

    layers, source = layers_from(args.export)
    print(f'network: {source}')
    total_macs = sum(n*k*c for _, n, k, c in layers)
    print(f'{len(layers)} convolutions, {total_macs/1e6:.1f} MMAC per image\n')

    configs = [('Channel', 8, 1), ('Channel', 16, 1), ('Channel', 32, 1),
               ('Channel', 64, 1),
               ('Bank', 8, 4), ('Bank', 16, 4), ('Bank', 16, 8), ('Bank', 32, 4)]

    if args.sparsity:
        print(f'SPARSE, assuming {args.sparsity:.1%} of activations nonzero and '
              f'a {args.imbalance:.3f}x bank imbalance.')
        print('That density is the VGG probe\'s, not CIFAR\'s: an assumption, '
              'not a measurement.\n')
    else:
        print('DENSE: every tap issued. An upper bound on cycles, assuming '
              'nothing about the activations.\n')

    print(f'{"core":<9}{"P":>4}{"T":>3}{"mult":>6}  ', end='')
    print(''.join(f'{name:>9}' for name, *_ in layers), end='')
    print(f'{"total":>11}{"ms":>8}{"fps":>7}')

    rows = []
    for name, p, t in configs:
        per_layer, total = [], 0
        for _, n, k, c in layers:
            if args.sparsity:
                nnz = max(1, round(k*args.sparsity))
                per = max(1, round(nnz/t*args.imbalance)) if t > 1 else nnz
            else:
                per = dense_per_group(k, t)
            cyc = n*per_window(k, c, p, t, per)
            per_layer.append(cyc)
            total += cyc
        f = FMAX.get((name, p, t))
        ms = total/(f*1000) if f else None
        rows.append((name, p, t, total, ms))
        print(f'{name:<9}{p:>4}{t:>3}{p*t:>6}  ', end='')
        print(''.join(f'{c/1000:>8.0f}k' for c in per_layer), end='')
        print(f'{total:>11,}', end='')
        print(f'{ms:>8.1f}{1000/ms:>7.0f}' if ms else f'{"-":>8}{"-":>7}')

    print('\nms and fps only where Fmax was measured on a routed design:')
    for (core, p, t), f in sorted(FMAX.items()):
        print(f'  {core} P={p} T={t}: {f:.1f} MHz')
    print('The others are cycles only. Cycles are geometry; a clock is a build.')

    # The floor. One activation enters the core per cycle whatever the issue
    # engine does, so no amount of parallelism gets a layer below its own K per
    # window. On this network that floor is most of the run, which is the thing
    # worth knowing before choosing what to build.
    floor = sum(n*k for _, n, k, _c in layers)
    print(f'\nFeed floor: {floor:,} cycles per image. The input port takes one '
          f'activation per cycle,')
    print(f'so no configuration goes below this. Reaching it needs P*T >= COUT '
          f'at every layer.')
    worst_layer = max(layers, key=lambda L: L[1]*L[2])
    print(f'{worst_layer[0]} alone is {worst_layer[1]*worst_layer[2]:,} of it '
          f'({worst_layer[1]*worst_layer[2]/floor:.0%}): {worst_layer[1]:,} '
          f'windows of K={worst_layer[2]}.')

    best = min((r for r in rows if r[4]), key=lambda r: r[4])
    print(f'\nOf the built configurations, {best[0]} P={best[1]} T={best[2]} is '
          f'fastest: {best[3]:,} cycles, {best[4]:.1f} ms, {1000/best[4]:.0f} fps')
    print(f'  -- {best[3]/floor:.2f}x the feed floor.')


if __name__ == '__main__':
    main()
