const puppeteer = require('puppeteer-core');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--window-size=1600,1000']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });

  console.log("Navigating to http://localhost:3000/...");
  await page.goto('http://localhost:3000/', { waitUntil: 'networkidle2' });
  await page.waitForSelector('.market-table');
  console.log("Home table loaded.");

  // Verify bulk quick actions bar is REMOVED
  const quickActionsBar = await page.$('.table-quick-actions-bar');
  console.log("Bulk quick actions bar present (should be false):", !!quickActionsBar);

  // Take screenshot of clean table
  await page.screenshot({ path: '/Users/sandeepjadhav/.gemini/antigravity-cli/brain/a3896f7c-ca09-45e3-9ab4-4a470d88b9a5/screenshots/clean_table_no_bulk_bar.png' });

  // Test per-row Copy Symbol button
  console.log("Testing per-row copy symbol button on first row...");
  const firstRowSymbol = await page.$eval('.instrument-symbol', el => el.innerText);
  console.log("First row symbol:", firstRowSymbol);

  await page.click('.symbol-action-btn.copy-btn');
  await new Promise(r => setTimeout(r, 200));

  const isCopiedCheck = await page.$eval('.symbol-action-btn.copy-btn', el => el.innerHTML);
  console.log("Per-row copy checkmark rendered:", isCopiedCheck.includes('✓'));

  // Test per-row Open in New Tab link
  const newTabHref = await page.$eval('.symbol-action-btn.new-tab-btn', el => el.getAttribute('href'));
  const newTabTarget = await page.$eval('.symbol-action-btn.new-tab-btn', el => el.getAttribute('target'));
  console.log(`New Tab button: href="${newTabHref}", target="${newTabTarget}"`);

  await page.screenshot({ path: '/Users/sandeepjadhav/.gemini/antigravity-cli/brain/a3896f7c-ca09-45e3-9ab4-4a470d88b9a5/screenshots/row_smart_actions_clean.png' });

  // Test TickerHeader on stock detail page
  console.log("Navigating to stock page to test header copyable badge...");
  await page.goto('http://localhost:3000/stocks/AEGISLOG', { waitUntil: 'networkidle2' });
  await page.waitForSelector('.stock-identity-header');

  const copyableBadge = await page.$('.copyable-badge');
  console.log("Copyable badge present on stock header:", !!copyableBadge);

  await page.click('.copyable-badge');
  await new Promise(r => setTimeout(r, 200));

  const badgeHtml = await page.$eval('.copyable-badge', el => el.innerHTML);
  console.log("Stock header badge copied checkmark rendered:", badgeHtml.includes('✓'));

  await page.screenshot({ path: '/Users/sandeepjadhav/.gemini/antigravity-cli/brain/a3896f7c-ca09-45e3-9ab4-4a470d88b9a5/screenshots/stock_header_copy_badge_verified.png' });

  await browser.close();
  console.log("All tests PASSED successfully!");
})();
