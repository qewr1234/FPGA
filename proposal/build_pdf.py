"""PROPOSAL_KO.md -> PROPOSAL_KO.pdf (A4), through HTML and headless Chromium.

    python proposal/build_pdf.py [--chrome PATH]

Needs the `markdown` package and a Chromium/Chrome binary. Korean text uses
Nanum Gothic, then Malgun Gothic, then whatever sans-serif the system has.
"""
import argparse
import shutil
import subprocess
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent

CSS = """
@page { size: A4; margin: 18mm 17mm 18mm 17mm; }
body { font-family: 'NanumGothic', 'Nanum Gothic', 'Malgun Gothic', sans-serif;
       font-size: 10.2pt; line-height: 1.62; color: #1d232a; }
h1 { font-size: 18pt; margin: 0 0 4pt; line-height: 1.3; }
h1 + p { color: #44505c; margin-top: 0; }
h2 { font-size: 13pt; border-bottom: 1.5px solid #c9d1d9; padding-bottom: 3pt;
     margin-top: 18pt; break-after: avoid; }
h3 { font-size: 11pt; margin-top: 12pt; break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9.2pt;
        break-inside: avoid; }
th, td { border: 1px solid #c9d1d9; padding: 3.5pt 6pt; vertical-align: top; }
th { background: #eef2f6; }
img { max-width: 100%; display: block; margin: 6pt auto; break-inside: avoid; }
code { font-family: 'NanumGothicCoding', monospace; font-size: 9pt; background: #f2f4f6;
       padding: 0 2pt; }
hr { border: none; border-top: 1px solid #c9d1d9; margin: 10pt 0; }
li { margin: 1.5pt 0; }
em { color: #44505c; }
"""


def find_chrome(explicit):
    if explicit:
        return explicit
    for c in ('chromium', 'chromium-browser', 'google-chrome', 'chrome',
              '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
              r'C:\Program Files\Google\Chrome\Application\chrome.exe',
              r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'):
        p = shutil.which(c) or (c if Path(c).exists() else None)
        if p:
            return p
    raise SystemExit('no Chromium/Chrome/Edge found; pass --chrome')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chrome')
    args = ap.parse_args()
    src = HERE/'PROPOSAL_KO.md'
    body = markdown.markdown(src.read_text(encoding='utf-8'), extensions=['tables'])
    html = HERE/'PROPOSAL_KO.html'
    html.write_text(f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                    f'<title>제안서</title><style>{CSS}</style></head><body>{body}</body></html>',
                    encoding='utf-8')
    pdf = HERE/'PROPOSAL_KO.pdf'
    subprocess.run([find_chrome(args.chrome), '--headless', '--disable-gpu', '--no-sandbox',
                    '--no-pdf-header-footer', f'--print-to-pdf={pdf}', html.as_uri()],
                   check=True, capture_output=True)
    html.unlink()
    print(f'wrote {pdf}')


if __name__ == '__main__':
    main()
