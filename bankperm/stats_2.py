"""Paired bootstrap intervals of the W=4 pooled savings of B-32 ReLU + QAT s1 (counts, not board runs).

    python bankperm/stats_2.py            # writes bankperm/stats_2.json (seconds; no emulation)

Network dn_d10_c32_us_fx_qat (count_test_sets.MODELS 'B-32 ReLU + QAT s1'), the
board network. Nothing is counted here: every per-image total is read from the
committed JSON files that counted it, all with the same rule (W=4 sparse
predict_w4.window_cycles summed over conv1-conv10, fill and drain left out;
Set12 + BSD68, sigma 25, test_noise seed 0, host emulation):

  b32_testsets.json  Original, and the published Frozen and Multi-start exports
                     (each counted on the emulation of its own export);
  skew_count.json    the skewed layout (PROTOCOL_2.md L2: bank (s + p) % 4 on the
                     inputs of conv2..conv9), against its own conventional count;
  baselines.json     the perfect-balance bound (per window max bank = ceil(nnz/4):
                     no static channel-to-bank layout can count less), the density
                     layouts (density_rr, density_snake, meannnz_lpt on C1 =
                     Set12 01.png, and the same on C3 = Set12 01-03) and the
                     equal-budget greedy (fit_group with 2004 proposals = 2005
                     objective evaluations per layer, Multi-start's budget; on C1
                     and on C3; optimizer seeds 42, 101, 202, 303, 404).

Evaluation sets: the 79 images other than Set12 01.png (C1's and Frozen's
calibration image; PROTOCOL.md's and PROTOCOL_2.md's headline set) and the 77
other than Set12 01-03 (C3's and Multi-start's calibration images). A layout
calibrated on C3 is not clean on the 79 (02 and 03 are its calibration images at
the same noise seed); the JSON says so per layout and set ('clean').

Saving of a layout = 100 * (sum Original - sum layout) / sum Original over the
images of the set (pooled). Difference A - B of two savings, in percentage
points = 100 * (sum B - sum A) / sum Original.

Bootstrap (paired over images): per evaluation set its own
np.random.default_rng(0), one draw rng.integers(0, n, size=(10000, n)) of image
indices (n images, with replacement; the convention of scripts/q1_fair_budget.py),
images in sorted (set, image) order (BSD68 test001..test068, then Set12), the
order bankperm/evaluate_2.py resamples the 79 in, so that the intervals of the
same quantities there (L1 = Frozen on this network, L2 = skew) come from the same
resamples; the same 10,000 resamples for every layout and difference of that set,
so the intervals are paired. 95% percentile interval:
np.percentile(values, [2.5, 97.5]) (numpy's default linear interpolation).
The equal-budget greedy is given for seed 42 and for the mean over the 5 seeds
(the per-image mean of the 5 totals; its pooled saving is the mean of the 5
seeds' pooled savings); its bootstrap resamples images only, not seeds.

Checks: the Original's per-image W=4 totals are equal in the three files (and in
denoise/test_set_counts.json and bankperm/results.json), the Original's W=1 and
W=2 totals are equal in b32_testsets.json and skew_count.json, the published
layouts' totals are equal in b32_testsets.json and baselines.json, and every
point estimate reproduces the saving its source file reports.
"""
import json
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LABEL, MODEL = 'B-32 ReLU + QAT s1', 'dn_d10_c32_us_fx_qat'
B, SEED, LEVEL = 10_000, 0, 95
OPT_SEEDS = (42, 101, 202, 303, 404)          # baselines.py OPT_SEEDS, the order of its per-image lists
SETS = {
    '79': ('all 80 but Set12 01.png (C1, Frozen\'s calibration image)', {('Set12', '01.png')}),
    '77': ('all 80 but Set12 01-03 (C3, Multi-start\'s calibration images)',
           {('Set12', '01.png'), ('Set12', '02.png'), ('Set12', '03.png')}),
}
# name: (source file, key in that file, calibration: None / 'C1' / 'C3', what)
LAYOUTS = {
    'frozen': ('b32_testsets.json', 'frozen', 'C1', 'published Frozen export (bank_export_perm.json)'),
    'multistart': ('b32_testsets.json', 'multistart', 'C3', 'published Multi-start export'),
    'skew': ('skew_count.json', 'skewed', None, 'PROTOCOL_2.md L2, bank (s + p) % 4, no calibration'),
    'perfect_balance': ('baselines.json', 'perfect_balance', None,
                        'bound: per window max bank = ceil(nnz/4); no static layout counts less'),
    'greedy_budget_c1_s42': ('baselines.json', ('greedy_budget_c1', 0), 'C1',
                             'equal-budget greedy (2005 evaluations per layer) on C1, seed 42'),
    'greedy_budget_c1_mean5': ('baselines.json', ('greedy_budget_c1', None), 'C1',
                               'equal-budget greedy on C1, per-image mean of the 5 seeds'),
    'greedy_budget_c3_s42': ('baselines.json', ('greedy_budget_c3', 0), 'C3',
                             'equal-budget greedy (2005 evaluations per layer) on C3, seed 42'),
    'greedy_budget_c3_mean5': ('baselines.json', ('greedy_budget_c3', None), 'C3',
                               'equal-budget greedy on C3, per-image mean of the 5 seeds'),
    'density_rr': ('baselines.json', 'density_rr', 'C1', 'density sort, round-robin, C1'),
    'density_snake': ('baselines.json', 'density_snake', 'C1', 'density sort, snake, C1'),
    'meannnz_lpt': ('baselines.json', 'meannnz_lpt', 'C1', 'mean-NNZ balance (LPT), C1'),
    'density_rr_c3': ('baselines.json', 'density_rr_c3', 'C3', 'density sort, round-robin, C3'),
    'density_snake_c3': ('baselines.json', 'density_snake_c3', 'C3', 'density sort, snake, C3'),
    'meannnz_lpt_c3': ('baselines.json', 'meannnz_lpt_c3', 'C3', 'mean-NNZ balance (LPT), C3'),
}
ASKED_DIFFERENCES = (('skew', 'multistart'), ('skew', 'frozen'))
EXTRA_DIFFERENCES = (('skew', 'greedy_budget_c1_mean5'), ('skew', 'greedy_budget_c3_mean5'),
                     ('perfect_balance', 'skew'), ('multistart', 'frozen'))


def load():
    b32 = json.loads((HERE/'b32_testsets.json').read_text())
    skew = json.loads((HERE/'skew_count.json').read_text())
    base = json.loads((HERE/'baselines.json').read_text())
    assert b32['model'] == MODEL and base['model'] == MODEL
    assert skew['networks'][LABEL]['model'] == MODEL
    order = sorted((r['set'], r['image']) for r in b32['images'])    # BSD68 test001..068, then Set12 01..12
    assert len(order) == 80 and len(set(order)) == 80
    rows = {(r['set'], r['image']): r for r in b32['images']}
    sk = skew['networks'][LABEL]['images']
    bl = base['per_image']
    assert set(sk) == {f'{s} {n}' for s, n in order} and set(bl) == {f'{s}/{n}' for s, n in order}
    return b32, skew, base, order, rows, sk, bl


def totals(order, rows, sk, bl):
    """Per-image W=4 totals (float64 arrays in image order) of the Original and every layout."""
    t = {'original': np.array([rows[k]['w4']['original'] for k in order], np.float64)}
    for name, (src, key, _, _) in LAYOUTS.items():
        if src == 'b32_testsets.json':
            v = [rows[k]['w4'][key] for k in order]
        elif src == 'skew_count.json':
            v = [sk[f'{s} {n}'][key]['w4'] for s, n in order]
        else:
            if isinstance(key, tuple):
                fam, i = key
                v = [(bl[f'{s}/{n}'][fam][i] if i is not None else float(np.mean(bl[f'{s}/{n}'][fam])))
                     for s, n in order]
            else:
                v = [bl[f'{s}/{n}'][key] for s, n in order]
        t[name] = np.asarray(v, np.float64)
    return t


def checks(b32, skew, base, order, rows, sk, bl, tot):
    c = {}
    o_b32 = [rows[k]['w4']['original'] for k in order]
    o_skew = [sk[f'{s} {n}']['conventional']['w4'] for s, n in order]
    o_base = [bl[f'{s}/{n}']['original'] for s, n in order]
    ref = json.loads((ROOT/'denoise'/'test_set_counts.json').read_text())['networks'][LABEL]
    assert ref['model'] == MODEL
    o_ref = [ref['sets'][s]['per_image'][n]['sparse_w4'] for s, n in order]
    res = json.loads((HERE/'results.json').read_text())['networks'][LABEL]
    assert res['model'] == MODEL
    o_res = [res['per_image'][f'{s}/{n}']['w4'][0] for s, n in order]
    p_res = [res['per_image'][f'{s}/{n}']['w4'][1] for s, n in order]
    eq = lambda a, b: sum(int(x) == int(y) for x, y in zip(a, b))  # noqa: E731
    c['original_w4_b32_testsets_eq_skew_count'] = f'{eq(o_b32, o_skew)}/80'
    c['original_w4_b32_testsets_eq_baselines'] = f'{eq(o_b32, o_base)}/80'
    c['original_w4_b32_testsets_eq_denoise_test_set_counts'] = f'{eq(o_b32, o_ref)}/80'
    c['original_w4_b32_testsets_eq_results_json'] = f'{eq(o_b32, o_res)}/80'
    for w in ('w1', 'w2'):
        c[f'original_{w}_b32_testsets_eq_skew_count'] = f'{eq([rows[k][w]["original"] for k in order], [sk[f"{s} {n}"]["conventional"][w] for s, n in order])}/80'
        c[f'skew_{w}_eq_original_{w}'] = f'{eq([sk[f"{s} {n}"]["skewed"][w] for s, n in order], [sk[f"{s} {n}"]["conventional"][w] for s, n in order])}/80'
    c['frozen_w4_b32_testsets_eq_baselines_frozen_published'] = (
        f'{eq([rows[k]["w4"]["frozen"] for k in order], [bl[f"{s}/{n}"]["frozen_published"] for s, n in order])}/80')
    c['multistart_w4_b32_testsets_eq_baselines_multistart_published'] = (
        f'{eq([rows[k]["w4"]["multistart"] for k in order], [bl[f"{s}/{n}"]["multistart_published"] for s, n in order])}/80')
    c['frozen_w4_b32_testsets_eq_results_json_permuted'] = (
        f'{eq([rows[k]["w4"]["frozen"] for k in order], p_res)}/80 (PROTOCOL.md H0: the recipe reproduces Frozen)')
    c['skew_count_layers_skewed_per_image'] = sorted({sk[f'{s} {n}']['layers_skewed'] for s, n in order})
    # point estimates against the figures the source files report
    ex1 = {s: SETS[s][1] for s in SETS}
    keep = {s: np.array([k not in ex1[s] for k in order]) for s in SETS}
    pooled = lambda m, name: float(100*(tot['original'][m].sum() - tot[name][m].sum())/tot['original'][m].sum())  # noqa: E731
    rep = []
    sm = b32['summaries']
    for es, lab in (('79', '79 without 01.png'), ('77', '77 without Set12 01-03')):
        for k in ('frozen', 'multistart'):
            rep.append((f'b32_testsets {lab} {k}', pooled(keep[es], k), sm[lab][k]['w4']['pooled']))
        bs = base['summary'][es]
        rep.append((f'baselines {es} perfect_balance', pooled(keep[es], 'perfect_balance'), bs['perfect_balance']['pooled_pct']))
        for k in ('density_rr', 'density_snake', 'meannnz_lpt', 'density_rr_c3', 'density_snake_c3', 'meannnz_lpt_c3'):
            rep.append((f'baselines {es} {k}', pooled(keep[es], k), bs['methods'][k]['pooled_pct']))
        for fam in ('greedy_budget_c1', 'greedy_budget_c3'):
            rep.append((f'baselines {es} {fam} seed 42', pooled(keep[es], f'{fam}_s42'),
                        bs['methods'][fam]['per_seed']['42']['pooled_pct']))
            rep.append((f'baselines {es} {fam} mean of 5 seeds', pooled(keep[es], f'{fam}_mean5'),
                        bs['methods'][fam]['pooled_pct_mean']))
    rep.append(('skew_count 79 skew', pooled(keep['79'], 'skew'),
                skew['board_network']['saving_percent_79_images_other_than_01']['w4']['pooled']))
    bad = [(n, a, b) for n, a, b in rep if abs(a - b) > 1e-3]       # the files round to 4 decimals
    c['point_estimates_reproduce_source_files'] = f'{len(rep) - len(bad)}/{len(rep)} (|difference| <= 1e-3 pp)'
    c['point_estimate_mismatches'] = bad
    ok = all(v.startswith('80/80') for k, v in c.items() if isinstance(v, str) and '/80' in v) and not bad
    c['all_ok'] = bool(ok and c['skew_count_layers_skewed_per_image'] == [8])
    return c


def ci(v):
    lo, hi = np.percentile(v, [(100 - LEVEL)/2, 100 - (100 - LEVEL)/2])
    return [round(float(lo), 4), round(float(hi), 4)]


def bootstrap(order, tot, es):
    excl = SETS[es][1]
    m = np.array([k not in excl for k in order])
    n = int(m.sum())
    sub = {k: v[m] for k, v in tot.items()}
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, n, size=(B, n))
    o = sub['original']
    O, Ob = o.sum(), o[idx].sum(1)
    sums = {k: (v.sum(), v[idx].sum(1)) for k, v in sub.items()}
    out = dict(images=n, excluded=sorted(f'{s} {i}' for s, i in excl), original_cycles=int(O), layouts={},
               differences_pp={})
    for name, (src, key, cal, what) in LAYOUTS.items():
        L, Lb = sums[name]
        s, sb = 100*(O - L)/O, 100*(Ob - Lb)/Ob
        per = 100*(o - sub[name])/o
        out['layouts'][name] = dict(
            what=what, source=f'bankperm/{src}', calibration=cal,
            clean=not (es == '79' and cal == 'C3'),
            pooled_saving_pct=round(float(s), 4), ci95_pct=ci(sb), bootstrap_se_pp=round(float(sb.std(ddof=1)), 4),
            per_image_min_pct=round(float(per.min()), 4), per_image_median_pct=round(float(np.median(per)), 4),
            per_image_max_pct=round(float(per.max()), 4), images_saving_le_0=int((per <= 0).sum()))
    for a, b in ASKED_DIFFERENCES + EXTRA_DIFFERENCES:
        (A, Ab), (Bv, Bb) = sums[a], sums[b]
        d, db = 100*(Bv - A)/O, 100*(Bb - Ab)/Ob
        per = 100*(sub[b] - sub[a])/o
        out['differences_pp'][f'{a} - {b}'] = dict(
            asked=(a, b) in ASKED_DIFFERENCES,
            clean=not (es == '79' and 'C3' in (LAYOUTS[a][2], LAYOUTS[b][2])),
            difference_pp=round(float(d), 4), ci95_pp=ci(db), bootstrap_se_pp=round(float(db.std(ddof=1)), 4),
            share_of_resamples_le_0=round(float((db <= 0).mean()), 4),
            ci_excludes_0=bool(ci(db)[0] > 0 or ci(db)[1] < 0),
            images_where_a_saves_more=int((per > 0).sum()), images_where_b_saves_more=int((per < 0).sum()),
            images_tied=int((per == 0).sum()))
    return out


def main():
    t0 = time.time()
    b32, skew, base, order, rows, sk, bl = load()
    tot = totals(order, rows, sk, bl)
    chk = checks(b32, skew, base, order, rows, sk, bl, tot)
    res = dict(
        network=LABEL, model=MODEL, what=('paired bootstrap intervals of W=4 pooled count savings against the '
                                         'Original; counts, not board measurements; nothing re-counted here'),
        count=('W=4 sparse window cycles max(ceil(K/4)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT), summed over '
               'conv1-conv10 (predict_w4.window_cycles); fill and drain left out; Set12 + BSD68, sigma 25, '
               'test_noise seed 0, host emulation'),
        saving='100 * (sum Original - sum layout) / sum Original over the images of the set',
        difference='A - B in percentage points = 100 * (sum B - sum A) / sum Original; > 0: A saves more',
        bootstrap=dict(resamples=B, generator=f'np.random.default_rng({SEED}), one per evaluation set',
                       draw='rng.integers(0, n, size=(10000, n)): image indices with replacement',
                       paired='the same resamples for every layout and difference of a set',
                       interval=f'{LEVEL}% percentile, np.percentile(values, [2.5, 97.5]) (linear)',
                       image_order=('sorted (set, image): BSD68 test001..test068, then Set12 (01..12 minus the '
                                    'excluded); the order of bankperm/evaluate_2.py\'s 79'),
                       not_resampled=('optimizer seeds (the 5-seed mean of the equal-budget greedy is a fixed '
                                      'per-image mean), noise realisations (test_noise seed 0 only)')),
        sources={'b32_testsets.json': 'Original, Frozen, Multi-start', 'skew_count.json': 'skew',
                 'baselines.json': 'perfect balance, density layouts, equal-budget greedy'},
        clean=('False where the layout (or a side of the difference) was calibrated on C3 = Set12 01-03 and the set '
               'is the 79, which contains 02 and 03'),
        checks=chk,
        sets={es: dict(what=SETS[es][0], **bootstrap(order, tot, es)) for es in SETS},
        seconds=round(time.time() - t0, 1))
    (HERE/'stats_2.json').write_text(json.dumps(res, indent=1) + '\n')
    for es, r in res['sets'].items():
        print(f'\n{es} images ({r["what"]}); pooled W=4 saving vs Original, 95% paired bootstrap')
        for name, v in r['layouts'].items():
            print(f'  {name:<24} {v["pooled_saving_pct"]:7.3f}%  [{v["ci95_pct"][0]:.3f}, {v["ci95_pct"][1]:.3f}]'
                  f'{"" if v["clean"] else "  (not clean: C3 on the 79)"}')
        for name, v in r['differences_pp'].items():
            print(f'  {name:<36} {v["difference_pp"]:+7.3f} pp  [{v["ci95_pp"][0]:+.3f}, {v["ci95_pp"][1]:+.3f}]'
                  f'  a>b on {v["images_where_a_saves_more"]}/{r["images"]} images'
                  f'{"" if v["clean"] else "  (not clean)"}')
    print('\nchecks', json.dumps(chk, indent=1))
    print('wrote bankperm/stats_2.json')


if __name__ == '__main__':
    main()
