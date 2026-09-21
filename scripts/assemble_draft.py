"""Assemble the paper sections and the four chosen figures into one HTML preview.

Not a typesetter -- it is a way to read the draft with its figures in place
before committing to a two-column layout. The figures are embedded as base64 so
the file can be opened or sent anywhere on its own.

A figure whose PNG is missing renders as a labelled box saying what to run,
rather than silently leaving a gap: fig8 needs data a board run leaves behind,
which is not in every checkout.

    python scripts/assemble_draft.py     ->  paper/paper_draft.html
"""
import base64, re
from pathlib import Path
R = Path('/home/user/FPGA'); F = R/'paper'/'figures'

FIGS = {  # where each figure is inserted, and its printed width
 1: ('fig1_architectures',  'paper/02_architecture.md', 'Fig. 1 shows the three structures side by side.', '100%'),
 2: ('fig2_iso_multiplier', 'paper/04_results.md', 'channels costs essentially nothing in throughput.', '52%'),
 3: ('fig7_scaling',        'paper/04_results.md', '| Difference | **-35%** | **-61%** |', '52%'),
 4: ('fig8_visual_check',   'paper/04_results.md', 'difference is uniformly zero.', '100%'),
}
CAPS = {
 1: 'Fig. 1. The three window-MAC structures. v3 replicates an accumulator per output lane; '
    'v4 sums P x T products in an adder tree and shares one accumulator behind it.',
 2: 'Fig. 2. Cycles per window against multipliers. The dashed arrow is the 85.9% comparison, '
    'which reads across the axis from 8 multipliers to 64. Reading vertically at 64 gives 5.1%.',
 3: 'Fig. 3. Post-route cost of adding one multiplier, for the configurations Vivado inferred '
    'no DSP blocks for. This is the result the paper rests on.',
 4: 'Fig. 4. Hardware against software on a complete 112 x 112 feature map. '
    'All 1,605,632 outputs match, so the difference map is uniformly zero.',
}

def img(stem, width):
    p = F/f'{stem}.png'
    if not p.exists():
        # A screenshot kept only so the draft can be read whole. It is a
        # rasterised capture, not the figure -- the real one is regenerated on
        # the machine that holds the board data.
        prev = F/f'{stem}_PREVIEW.png'
        if prev.exists():
            b64 = base64.b64encode(prev.read_bytes()).decode()
            return (f'<img src="data:image/png;base64,{b64}" style="width:{width}">'
                    f'<div class="provisional">PREVIEW ONLY -- a screenshot, not the '
                    f'figure. Regenerate with <code>python paper/figures/'
                    f'fig8_visual_check.py --channel 125</code> on the machine with '
                    f'the board data, and use the PDF it writes.</div>')
        return (f'<div class="missing"><b>{stem}.png is not in this container.</b><br>'
                f'It needs the data a board run leaves behind. Rebuild it on your machine with '
                f'<code>python paper/figures/fig8_visual_check.py --channel 125</code>'
                f' and this box becomes the figure.</div>')
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f'<img src="data:image/png;base64,{b64}" style="width:{width}">'

body = []
for src in ['paper/01_introduction.md','paper/02_architecture.md','paper/03_method.md',
            'paper/04_results.md','paper/05_discussion.md']:
    t = (R/src).read_text(encoding='utf-8')
    for n,(stem, where, anchor, w) in FIGS.items():
        if where == src and anchor in t:
            block = f'\n\n<figure>{img(stem,w)}<figcaption>{CAPS[n]}</figcaption></figure>\n\n'
            t = t.replace(anchor, anchor + block, 1)
    body.append(t)

md = '\n\n'.join(body)

# very small markdown -> html, enough for a draft preview
def md2html(s):
    out, in_tbl, in_code = [], False, False
    for line in s.split('\n'):
        if line.startswith('```'):
            in_code = not in_code; out.append('<pre><code>' if in_code else '</code></pre>'); continue
        if in_code: out.append(line.replace('&','&amp;').replace('<','&lt;')); continue
        if line.startswith('<'): out.append(line); continue
        if line.startswith('|'):
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if set(''.join(cells)) <= set('-: '):
                continue
            tag = 'th' if not in_tbl else 'td'
            if not in_tbl: out.append('<table>'); in_tbl = True
            out.append('<tr>' + ''.join(f'<{tag}>{c}</{tag}>' for c in cells) + '</tr>')
            continue
        if in_tbl: out.append('</table>'); in_tbl = False
        for lvl in (4,3,2,1):
            if line.startswith('#'*lvl + ' '):
                out.append(f'<h{lvl}>{line[lvl+1:]}</h{lvl}>'); break
        else:
            out.append('<p>'+line+'</p>' if line.strip() else '')
    if in_tbl: out.append('</table>')
    h = '\n'.join(out)
    h = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', h)
    h = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<em>\1</em>', h)
    h = re.sub(r'`([^`]+?)`', r'<code>\1</code>', h)
    return h

HTML = f"""<!doctype html><meta charset="utf-8"><title>Paper draft</title>
<style>
 body{{max-width:46em;margin:3em auto;padding:0 1.5em;
      font:15px/1.65 Georgia,'Times New Roman',serif;color:#1a1a1a}}
 h1{{font-size:1.7em}} h2{{font-size:1.25em;margin-top:2.2em;border-bottom:1px solid #ddd;padding-bottom:.2em}}
 h3{{font-size:1.05em;margin-top:1.6em}}
 table{{border-collapse:collapse;margin:1.2em 0;font-size:.88em;width:100%}}
 th,td{{border:1px solid #ccc;padding:.35em .6em;text-align:left}}
 th{{background:#f4f4f4}}
 code{{font:.88em ui-monospace,Menlo,Consolas,monospace;background:#f4f4f4;padding:.1em .3em;border-radius:3px}}
 pre{{background:#f7f7f7;border:1px solid #e3e3e3;border-radius:4px;padding:.8em;overflow-x:auto}}
 pre code{{background:none;padding:0}}
 figure{{margin:2em 0;text-align:center}}
 figure img{{border:1px solid #e0e0e0}}
 figcaption{{font-size:.82em;color:#555;text-align:left;margin-top:.6em;line-height:1.5}}
 .provisional{{border:2px dashed #c60;background:#fff8f0;color:#853;padding:.6em .9em;
              font:.8em/1.5 ui-monospace,Menlo,Consolas,monospace;text-align:left;
              margin-top:.5em;border-radius:4px}}
 .missing{{border:2px dashed #c33;color:#933;padding:1.4em;font-size:.9em;text-align:left;
          background:#fff6f6;border-radius:4px}}
</style>
{md2html(md)}
"""
out = R/'paper'/'paper_draft.html'
out.write_text(HTML, encoding='utf-8')
print('wrote', out, f'({out.stat().st_size/1024:.0f} KB)')
