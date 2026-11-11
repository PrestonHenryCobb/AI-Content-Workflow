// Re-render the audit screenshots of site/privacy.html into docs/audit_evidence/.
//   node scripts/screenshot_site.js        (needs the `playwright` package and Chromium)
const { chromium } = require('playwright');
const path = require('path');
const root = path.resolve(__dirname, '..');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1100, height: 900 }, deviceScaleFactor: 2 });
  await p.goto('file://' + root + '/site/privacy.html');
  const out = (n) => path.join(root, 'docs/audit_evidence', n);
  await p.screenshot({ path: out('privacy_policy_full.png'), fullPage: true });
  await p.screenshot({ path: out('privacy_1_youtube_api_services_and_data.png'),
                       clip: { x: 0, y: 0, width: 1100, height: 1150 } });
  await p.screenshot({ path: out('privacy_2_storage_sharing_retention_deletion.png'),
                       clip: { x: 0, y: 1130, width: 1100, height: 1300 }, fullPage: true });
  await b.close();
})();

// Terms of Service evidence (YouTube Terms of Service link boxed, screenshot-only overlay)
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1100, height: 900 }, deviceScaleFactor: 2 });
  await p.goto('file://' + root + '/site/terms.html');
  await p.evaluate(() => {
    for (const a of document.querySelectorAll('a[href="https://www.youtube.com/t/terms"]')) {
      a.style.outline = '3px solid #ff3b30'; a.style.outlineOffset = '4px';
    }
  });
  await p.screenshot({ path: path.join(root, 'docs/audit_evidence/terms_of_service_full.png'),
                       fullPage: true });
  await b.close();
})();
