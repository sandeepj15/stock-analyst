const puppeteer = require('puppeteer-core');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--window-size=1440,900']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  page.on('console', msg => console.log('BROWSER CONSOLE:', msg.text()));
  page.on('pageerror', err => console.log('BROWSER ERROR:', err.message));

  console.log("Navigating to Home / ...");
  const t0 = Date.now();
  await page.goto('http://localhost:3000/', { waitUntil: 'networkidle2' });
  console.log(`Home loaded in ${Date.now() - t0}ms, URL: ${page.url()}`);

  // Wait for table to be ready
  await page.waitForSelector('.row-link');
  console.log("Table rendered. Clicking AEGISLOG row...");

  const tNavStart = Date.now();
  await page.evaluate(() => {
    const symbols = Array.from(document.querySelectorAll('.instrument-symbol'));
    const target = symbols.find(s => s.textContent.trim() === 'AEGISLOG');
    if (target) {
      target.closest('tr').click();
    }
  });
  console.log("Clicked row via evaluate. Waiting for URL to become /stocks/AEGISLOG...");

  await page.waitForFunction(() => window.location.pathname.includes('/stocks/'), { timeout: 10000 });
  console.log("Client transition started. URL:", page.url());

  await page.waitForSelector('.stock-identity-header', { timeout: 15000 });
  const tNavEnd = Date.now();
  console.log(`Navigated to AEGISLOG stock page in ${tNavEnd - tNavStart}ms!`);

  // Verify breadcrumb exists
  const breadcrumb = await page.$('.breadcrumb-back-btn');
  console.log("Breadcrumb button present:", !!breadcrumb);

  await page.screenshot({ path: '/Users/sandeepjadhav/.gemini/antigravity-cli/brain/a3896f7c-ca09-45e3-9ab4-4a470d88b9a5/screenshots/stock_with_breadcrumb.png' });

  // Now click Back to Dashboard
  console.log("Clicking Back to Dashboard breadcrumb...");
  const tBackStart = Date.now();
  await page.evaluate(() => {
    document.querySelector('.breadcrumb-back-btn').click();
  });

  await page.waitForFunction(() => window.location.pathname === '/', { timeout: 10000 });
  await page.waitForSelector('.market-table', { timeout: 10000 });
  const tBackEnd = Date.now();
  console.log(`Navigated back to Home Dashboard in ${tBackEnd - tBackStart}ms!`);

  await page.screenshot({ path: '/Users/sandeepjadhav/.gemini/antigravity-cli/brain/a3896f7c-ca09-45e3-9ab4-4a470d88b9a5/screenshots/home_back_success.png' });

  // Now test brand link navigation back to home
  console.log("Navigating to second stock row...");
  await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('tr.row-link'));
    if (rows.length > 1) rows[1].click();
  });
  await page.waitForFunction(() => window.location.pathname.startsWith('/stocks/'), { timeout: 10000 });
  await page.waitForSelector('.stock-identity-header', { timeout: 15000 });
  console.log("Navigated to second stock page! Current URL:", page.url());

  console.log("Clicking SignalForge brand logo in topnav...");
  const tBrandStart = Date.now();
  await page.evaluate(() => {
    document.querySelector('a.brand').click();
  });
  await page.waitForFunction(() => window.location.pathname === '/', { timeout: 10000 });
  await page.waitForSelector('.market-table', { timeout: 10000 });
  const tBrandEnd = Date.now();
  console.log(`Navigated back to Home via brand logo in ${tBrandEnd - tBrandStart}ms!`);

  await page.screenshot({ path: '/Users/sandeepjadhav/.gemini/antigravity-cli/brain/a3896f7c-ca09-45e3-9ab4-4a470d88b9a5/screenshots/brand_back_success.png' });

  await browser.close();
  console.log("Navigation test suite passed with flying colors!");
})();
