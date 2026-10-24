// Render EXPLAINER_KO.html to EXPLAINER_KO.pdf with headless Chromium (Playwright).
//   node bankperm/explainer/render.js
const path = require('path');
const { chromium } = require('playwright');
(async () => {
  const here = __dirname;
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + path.join(here, 'EXPLAINER_KO.html'), { waitUntil: 'networkidle' });
  await page.pdf({
    path: path.join(here, 'EXPLAINER_KO.pdf'), format: 'A4', printBackground: true, preferCSSPageSize: true, outline: true, tagged: true,
    displayHeaderFooter: true, headerTemplate: '<div></div>',
    footerTemplate: '<div style="width:100%;font-size:7.5pt;color:#777;text-align:center;font-family:Noto Sans CJK KR,sans-serif">' +
      '논문 해설 · <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
  });
  await browser.close();
  console.log('wrote', path.join(here, 'EXPLAINER_KO.pdf'));
})();
