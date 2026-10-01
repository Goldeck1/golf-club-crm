import { chromium } from 'playwright';
import { mkdir } from 'fs/promises';

const url = 'https://akola.it-reu.ru/portal/nozdryakov_multipage_2026';
const outDir = '/tmp/akola_screenshots';
await mkdir(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.setViewportSize({ width: 1440, height: 900 });

console.log('Navigating...');
await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(3000);

await page.screenshot({ path: `${outDir}/01_main.png`, fullPage: false });
await page.screenshot({ path: `${outDir}/01_main_full.png`, fullPage: true });
console.log('Screenshot done');

const title = await page.title();
const allText = await page.evaluate(() => document.body.innerText.slice(0, 5000));
const links = await page.evaluate(() => {
  return [...document.querySelectorAll('a')].map(a => ({text: a.textContent?.trim().slice(0,80), href: a.href})).filter(l => l.href && l.text);
});
console.log('TITLE:', title);
console.log('=== PAGE TEXT ===');
console.log(allText);
console.log('=== LINKS ===');
console.log(JSON.stringify(links, null, 2));
await browser.close();
