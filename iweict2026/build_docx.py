"""Fill the IWEICT Word template from the Markdown draft.

    python iweict2026/build_docx.py --tpl <template_word.docx> --src iweict2026/PAPER_KO.md --out iweict2026/PAPER_KO.docx
    python iweict2026/build_docx.py --tpl <template_word.docx> --src iweict2026/PAPER_EN.md --out iweict2026/PAPER_EN.docx --lang en

The template's own styles are used for everything (paper title, Author,
Affiliation, Abstract, key words, heading 1/2 with their automatic I./A.
numbering, Body Text, figure caption, table head, table copy, references,
the unnumbered heading 5 for Acknowledgment and References). Wide tables are
put in a one-column section between two column breaks so they span both
columns, as the IEEE template does.

Markdown conventions the converter understands:
  # Title                           -> paper title (one line)
  a line '(저자 이름), (소속...)'    -> replaced by --authors / --affil / --email
                                       (and --author2 / --affil2 / --email2 for a second
                                       affiliation beside it, in the template's two author columns)
  ## 초록 / ## Abstract             -> Abstract paragraph(s)
  **주제어** — ... / **Keywords** — -> key words
  ## I. 서론  (any roman numeral)   -> heading 1 (the numeral is stripped; Word numbers it)
  ## 참고문헌 / ## References        -> heading 5 + references style per '[n] ...' paragraph
  **Lead.** text                    -> Body Text with a bold lead-in
  ![..](path) + *caption*           -> picture + figure caption
  *표 I. caption* + | table |       -> table head + table
  |------|---| separator row        -> column widths in those proportions (all equal: the defaults)
  - bullets                         -> Body Text paragraphs without indent (the template's bullet list style)
  > blockquote (draft memo)          -> dropped
  *( ... )* italic-only lines        -> dropped (translation notes)
"""
import argparse
import copy
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph

ROOT = Path(__file__).resolve().parents[1]


def set_east_asia_font(doc, name):
    """The template's default East Asian font is SimSun; Korean text needs a Hangul font."""
    styles = doc.styles.element
    for rfonts in styles.iter(qn('w:rFonts')):
        if rfonts.get(qn('w:eastAsia')) in ('SimSun', 'MS Mincho'):
            rfonts.set(qn('w:eastAsia'), name)
    dd = styles.find(qn('w:docDefaults'))
    if dd is not None:
        for rfonts in dd.iter(qn('w:rFonts')):
            rfonts.set(qn('w:eastAsia'), name)


def no_numbering(p):
    """Turn off the style's automatic numbering on this paragraph (numId 0)."""
    pPr = p._p.get_or_add_pPr()
    numPr = OxmlElement('w:numPr')
    ilvl = OxmlElement('w:ilvl'); ilvl.set(qn('w:val'), '0')
    numId = OxmlElement('w:numId'); numId.set(qn('w:val'), '0')
    numPr.append(ilvl); numPr.append(numId)
    # schema order: pStyle, keepNext, keepLines, pageBreakBefore, framePr, widowControl, numPr, ...
    anchor = None
    for tag in ('w:widowControl', 'w:framePr', 'w:pageBreakBefore', 'w:keepLines', 'w:keepNext', 'w:pStyle'):
        anchor = pPr.find(qn(tag))
        if anchor is not None:
            break
    if anchor is not None:
        anchor.addnext(numPr)
    else:
        pPr.insert(0, numPr)


def add_runs(p, text, bold_lead=False):
    """Markdown **bold**, *italic*, `code` inside a paragraph -> runs."""
    parts = re.split(r'(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)', text)
    for part in parts:
        if not part:
            continue
        if part.startswith('**'):
            r = p.add_run(part[2:-2]); r.bold = True
        elif part.startswith('*'):
            r = p.add_run(part[1:-1]); r.italic = True
        elif part.startswith('`'):
            r = p.add_run(part[1:-1]); r.font.name = 'Courier New'
        else:
            p.add_run(part)


def make_paragraph(doc, style, text='', **kw):
    p = doc.add_paragraph(style=style)
    if text:
        add_runs(p, text, **kw)
    return p


def set_cell_borders(tbl):
    tblPr = tbl._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'bottom', 'insideH'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single'); el.set(qn('w:sz'), '4'); el.set(qn('w:space'), '0'); el.set(qn('w:color'), '000000')
        borders.append(el)
    # schema order inside tblPr: ... tblInd, tblBorders, shd, tblLayout, tblCellMar, tblLook
    after = None
    for tag in ('w:shd', 'w:tblLayout', 'w:tblCellMar', 'w:tblLook', 'w:tblCaption', 'w:tblDescription'):
        after = tblPr.find(qn(tag))
        if after is not None:
            break
    if after is not None:
        after.addprevious(borders)
    else:
        tblPr.append(borders)


class Rows(list):
    """A table's rows; rel_widths is set when the separator row's dash counts differ (|----|--|: 2:1)."""
    rel_widths = None


def make_table(doc, rows, widths_cm):
    ncol = len(rows[0])
    tbl = doc.add_table(rows=len(rows), cols=ncol)
    tbl.autofit = False
    set_cell_borders(tbl)
    for j, w in enumerate(widths_cm):
        tbl.columns[j].width = Cm(w)          # the grid widths, which LibreOffice and Word lay out by
    for i, row in enumerate(rows):
        for j, cell_text in enumerate(row):
            cell = tbl.cell(i, j)
            cell.width = Cm(widths_cm[j])
            p = cell.paragraphs[0]
            p.style = doc.styles['table col head' if i == 0 else 'table copy']
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            add_runs(p, cell_text.replace('<br>', ' '))
            if j > 0:
                p.alignment = 1  # center
    return tbl


def section_break(doc, cols, space_twips, continuous=True):
    """A paragraph carrying a sectPr: everything before it is laid out with `cols` columns."""
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    sectPr = copy.deepcopy(doc.sections[-1]._sectPr)
    for child in list(sectPr):
        if child.tag in (qn('w:cols'), qn('w:type'), qn('w:headerReference'), qn('w:footerReference')):
            sectPr.remove(child)
    if continuous:
        t = OxmlElement('w:type'); t.set(qn('w:val'), 'continuous'); sectPr.insert(0, t)
    c = OxmlElement('w:cols'); c.set(qn('w:space'), str(space_twips))
    if cols > 1:
        c.set(qn('w:num'), str(cols))
    # keep schema order: cols must come after pgMar and before docGrid
    docgrid = sectPr.find(qn('w:docGrid'))
    if docgrid is not None:
        docgrid.addprevious(c)
    else:
        sectPr.append(c)
    pPr.append(sectPr)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    for r in p.runs:
        r.font.size = Pt(1)
    return p


def parse_markdown(md):
    """Yield (kind, payload) blocks in document order."""
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip() or ln.strip() == '---' or ln.startswith('>'):
            i += 1; continue
        if ln.startswith('# '):
            yield 'title', ln[2:].strip(); i += 1; continue
        if ln.startswith('## '):
            yield 'h1', ln[3:].strip(); i += 1; continue
        if ln.startswith('### '):
            yield 'h2', ln[4:].strip(); i += 1; continue
        if ln.startswith('!['):
            m = re.match(r'!\[[^\]]*\]\(([^)]+)\)', ln)
            cap = ''
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].startswith('*') and lines[j].endswith('*'):
                cap = lines[j].strip('*'); j += 1
            yield 'figure', (m.group(1), cap); i = j; continue
        if ln.startswith('|'):
            rows = Rows()
            while i < len(lines) and lines[i].startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', c) for c in cells):
                    rows.append(cells)
                elif len({c.count('-') for c in cells}) > 1:
                    rows.rel_widths = [c.count('-') for c in cells]
                i += 1
            yield 'table', rows; continue
        if ln.startswith('*') and ln.endswith('*') and not ln.startswith('**'):
            # italic-only line: a table caption if a table follows, else a note to drop
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].startswith('|'):
                yield 'tablehead', ln.strip('*'); i += 1; continue
            i += 1; continue
        if ln.startswith('- '):
            yield 'bullet', ln[2:].strip(); i += 1; continue
        if ln.startswith('  ') and ln.strip():
            yield 'equation', ln.strip(); i += 1; continue
        if re.match(r'\[\d+\] ', ln):
            yield 'ref', re.sub(r'^\[\d+\] ', '', ln).strip(); i += 1; continue
        if ln.startswith('(') and ('저자' in ln or 'Author' in ln):
            yield 'authors', ln; i += 1; continue
        # paragraph: join wrapped lines
        buf = [ln.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#|!\[|\||- |\*|\[\d+\] |  )', lines[i]):
            buf.append(lines[i].strip()); i += 1
        yield 'para', ' '.join(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tpl', type=Path, required=True)
    ap.add_argument('--src', type=Path, default=ROOT/'iweict2026'/'PAPER_KO.md')
    ap.add_argument('--out', type=Path, default=None)
    ap.add_argument('--lang', default='ko', choices=['ko', 'en'])
    ap.add_argument('--authors', default='(저자 이름)')
    ap.add_argument('--affil', default='(학과), (대학교)', help='one line; use ; to split lines')
    ap.add_argument('--email', default='')
    ap.add_argument('--author2', default=None, help='a second affiliation block beside the first')
    ap.add_argument('--affil2', default='', help='its lines; use ; to split lines')
    ap.add_argument('--email2', default='')
    ap.add_argument('--col-fig-cm', type=float, default=8.4, help='width of one-column figures')
    ap.add_argument('--wide-fig-cm', type=float, default=15.0, help='width of two-column figures')
    ap.add_argument('--ack', default='본 연구는 과학기술정보통신부 및 정보통신기획평가원의 "SW중심대학사업" 지원을 받아 수행되었습니다.')
    ap.add_argument('--east-asia-font', default='Malgun Gothic')
    args = ap.parse_args()
    out = args.out or args.src.with_suffix('.docx')

    doc = Document(str(args.tpl))
    set_east_asia_font(doc, args.east_asia_font)
    body = doc.element.body

    # --- locate the template's skeleton: title paragraph, author block, section-break paragraphs
    paras = list(body.iterchildren())
    def style_of(el):
        ps = el.find(qn('w:pPr') + '/' + qn('w:pStyle')) if el.tag == qn('w:p') else None
        return ps.get(qn('w:val')) if ps is not None else None
    def is_sect(el):
        return el.tag == qn('w:p') and el.find(qn('w:pPr') + '/' + qn('w:sectPr')) is not None
    sect_breaks = [el for el in paras if is_sect(el)]
    assert len(sect_breaks) >= 4, 'unexpected template layout'
    sb_title, sb_authors, sb_gap, sb_body = sect_breaks[:4]
    # everything after the author block up to the body's section break is template text: drop it
    el = sb_gap.getnext()
    while el is not None and el is not sb_body:
        nxt = el.getnext(); body.remove(el); el = nxt
    # the gap section's own paragraph may hold the sponsors text box: drop its runs
    for r in list(sb_gap.findall(qn('w:r'))):
        sb_gap.remove(r)
    # second affiliation block (the template has two): drop the paragraphs after the first block
    first_block = []
    el = sb_title.getnext()
    while el is not None and el is not sb_authors:
        first_block.append(el); el = el.getnext()
    two = args.author2 is not None
    authors = [e for e in first_block if style_of(e) == 'Author']
    # the author block's section-break paragraph is the second block's last line
    all_affils = [e for e in first_block if style_of(e) == 'Affiliation'] + [sb_authors]
    affils, affils2 = all_affils[:4], all_affils[4:8]
    for e in first_block:
        if e not in (authors[:1] + affils + (authors[1:2] + affils2 if two else [])):
            body.remove(e)
    if not two:
        # one affiliation: keep the section break, drop the second block's last line
        for r in list(sb_authors.findall(qn('w:r'))):
            sb_authors.remove(r)

    def set_text(el, text):
        runs = el.findall(qn('w:r'))
        for r in runs[1:]:
            el.remove(r)
        if runs:
            ts = runs[0].findall(qn('w:t'))
            for t in ts[1:]:
                runs[0].remove(t)
            if ts:
                ts[0].text = text; ts[0].set(qn('xml:space'), 'preserve')
                return
        r = OxmlElement('w:r'); t = OxmlElement('w:t'); t.text = text; t.set(qn('xml:space'), 'preserve'); r.append(t); el.append(r)

    # --- walk the Markdown
    blocks = list(parse_markdown(args.src.read_text(encoding='utf-8')))
    title = next(p for k, p in blocks if k == 'title')
    title_el = next(e for e in paras if style_of(e) == 'papertitle')
    set_text(title_el, title)
    set_text(authors[0], args.authors)
    affil_lines = [s.strip() for s in args.affil.split(';')] + ([args.email] if args.email else [])
    for e, line in zip(affils, affil_lines + [''] * 4):
        if line:
            set_text(e, line)
        else:
            body.remove(e)
    if two:
        # the second affiliation, beside the first in the template's two author columns
        set_text(authors[1], args.author2)
        affil2_lines = [s.strip() for s in args.affil2.split(';')] + ([args.email2] if args.email2 else [])
        for e, line in zip(affils2, affil2_lines + [''] * 4):
            if line or e is sb_authors:
                set_text(e, line)
            else:
                body.remove(e)
    # the author block section should be one column since there is one affiliation
    cols = sb_authors.find(qn('w:pPr') + '/' + qn('w:sectPr') + '/' + qn('w:cols'))
    if cols is not None and not two:
        for c in list(cols):
            cols.remove(c)
        cols.attrib.pop(qn('w:num'), None); cols.attrib.pop(qn('w:equalWidth'), None)

    # new content goes before sb_body; doc.add_paragraph appends at the end, so move each element
    def place(el):
        sb_body.addprevious(el)

    # Wide figures and tables go in a one-column section. Consecutive wide items
    # share one section, so no empty two-column strip is left between them.
    wide_state = {'open': False}

    def open_wide():
        if not wide_state['open']:
            place(section_break(doc, 2, 360)._p)        # ends the two-column text before it
            wide_state['open'] = True

    def close_wide():
        if wide_state['open']:
            place(section_break(doc, 1, 720)._p)        # ends the one-column wide section
            wide_state['open'] = False

    in_refs = False
    in_abstract = False
    abstract_done = False
    H1 = doc.styles['heading 1']
    ref_n = 0
    for kind, payload in blocks:
        if kind in ('title', 'authors'):
            continue
        is_wide = (kind == 'figure' and any(k in payload[0] for k in ('psnr_vs_cycles', 'board'))) or \
                  (kind == 'table' and len(payload[0]) >= 6) or kind == 'tablehead'
        if not is_wide:
            close_wide()
        if kind == 'h1':
            text = payload
            if text in ('초록', 'Abstract'):
                in_abstract = True; continue
            if text in ('참고문헌', 'References'):
                # acknowledgment first, then references
                p = make_paragraph(doc, 'heading 5', '사사' if args.lang == 'ko' else 'Acknowledgment'); place(p._p)
                p = make_paragraph(doc, 'Body Text', args.ack); place(p._p)
                p = make_paragraph(doc, 'heading 5', text); place(p._p)
                in_refs = True; continue
            text = re.sub(r'^[IVX]+\.\s*', '', text)
            p = doc.add_paragraph(style=H1); add_runs(p, text); place(p._p); continue
        if kind == 'h2':
            p = make_paragraph(doc, 'heading 2', re.sub(r'^[A-Z]\.\s*', '', payload)); place(p._p); continue
        if kind == 'ref':
            ref_n += 1
            p = make_paragraph(doc, 'references', payload); place(p._p); continue
        if kind == 'para':
            if in_abstract:
                m = re.match(r'^\*\*(주제어|Keywords)\*\*\s*[—-]\s*(.*)$', payload)
                if m:
                    p = make_paragraph(doc, 'key words', ('주제어—' if args.lang == 'ko' else 'Keywords—') + m.group(2))
                    place(p._p); in_abstract = False; abstract_done = True; continue
                p = make_paragraph(doc, 'Abstract', ('초록—' if args.lang == 'ko' else 'Abstract—') + payload)
                place(p._p); continue
            if payload.startswith('**사사') or payload.startswith('**Acknowledg'):
                continue  # the acknowledgment is written from --ack
            p = doc.add_paragraph(style='Body Text'); add_runs(p, payload); place(p._p); continue
        if kind == 'bullet':
            p = doc.add_paragraph(style='Body Text'); p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.left_indent = Cm(0.35)
            add_runs(p, '• ' + payload); place(p._p); continue
        if kind == 'equation':
            p = doc.add_paragraph(style='Body Text'); p.paragraph_format.first_line_indent = Cm(0); p.alignment = 1
            add_runs(p, payload); place(p._p); continue
        if kind == 'figure':
            path, cap = payload
            img = (args.src.parent / path).resolve()
            p = doc.add_paragraph(); p.alignment = 1; p.paragraph_format.first_line_indent = Cm(0)
            wide = 'psnr_vs_cycles' in str(img) or 'board' in str(img)
            if wide:
                open_wide()
            p.add_run().add_picture(str(img), width=Cm(args.wide_fig_cm if wide else args.col_fig_cm))
            place(p._p)
            c = make_paragraph(doc, 'figure caption'); no_numbering(c); add_runs(c, cap); place(c._p)
            continue
        if kind == 'tablehead':
            pending_head = payload; continue
        if kind == 'table':
            rows = payload
            ncol = len(rows[0])
            wide = ncol >= 6
            total = 17.0 if wide else 8.4
            first = 0.30 if ncol >= 7 else (0.34 if ncol == 6 else 0.30)
            widths = [total * first] + [total * (1 - first) / (ncol - 1)] * (ncol - 1)
            if getattr(rows, 'rel_widths', None):
                widths = [total * w / sum(rows.rel_widths) for w in rows.rel_widths]
            if wide:
                open_wide()
            h = make_paragraph(doc, 'table head'); no_numbering(h); add_runs(h, pending_head); place(h._p)
            tbl = make_table(doc, rows, widths); place(tbl._tbl)
            continue
    close_wide()
    # the template's last paragraph is empty, holds the final section break and has the
    # numbered references style: Word would print an extra '[n]' after the last reference
    if not sb_body.findall('.//' + qn('w:t')):
        no_numbering(Paragraph(sb_body, None))
    doc.save(str(out))
    print('wrote', out)


if __name__ == '__main__':
    main()
