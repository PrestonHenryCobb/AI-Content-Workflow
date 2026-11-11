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
