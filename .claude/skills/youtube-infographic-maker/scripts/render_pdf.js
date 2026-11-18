// Node/Playwright renderer used by render_pdf.py (same output as the Python path).
// Usage: node render_pdf.js <html> <pdf> <Letter|A4> [preview.png]
const { chromium } = require('playwright');
const path = require('path');
const { pathToFileURL } = require('url');

const [, , html, pdf, format = 'Letter', preview] = process.argv;
const FOOTER = '<div style="width:100%;font-size:7pt;color:#8a8f98;font-family:Arial,sans-serif;' +
  'padding:0 0.5in;display:flex;justify-content:space-between;"><span class="title"></span>' +
  '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>';

(async () => {
  let browser;
  try { browser = await chromium.launch(); }
  catch (e) { browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' }); }
  const page = await browser.newPage();
  await page.goto(pathToFileURL(path.resolve(html)).href, { waitUntil: 'networkidle' });
  await page.emulateMedia({ media: 'print' });
  await page.pdf({
    path: pdf, format, printBackground: true, preferCSSPageSize: format === 'Letter',
    displayHeaderFooter: true, headerTemplate: '<div></div>', footerTemplate: FOOTER,
    margin: { top: '0.45in', bottom: '0.6in', left: '0.5in', right: '0.5in' },
  });
  if (preview) {
    await page.emulateMedia({ media: 'screen' });
    await page.setViewportSize({ width: 850, height: 1100 });
    await page.screenshot({ path: preview, fullPage: true });
  }
  await browser.close();
})().catch((e) => { console.error(e.message); process.exit(1); });
