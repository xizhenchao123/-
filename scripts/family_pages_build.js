/* v17.28b: 家人版 GitHub Pages 组包脚本（零凭据，替代 Cloudflare Pages 方案）
   电脑关机照常更新：jd-cloud-feed 抓数后由 jd-family-pages workflow 调用本脚本，
   读 appsync/ 模板 + 最新现货价 → 组装到仓库 family/ 子目录 → workflow git 自提交，
   GitHub Pages 静态伺服 https://xizhenchao123.github.io/-/family/jd2611.html
   用法: node scripts/family_pages_build.js
   说明: 线上家人版无 /api/spot 代理（GitHub Pages 纯静态），SPOT_SEED 种子即其现货来源，
         页面 autoSpot() fetch 失败自动降级读种子末值（gap≤3 天有效）——种子保鲜即数据保鲜。 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.join(__dirname, '..');            /* 仓库根 */
const SRC  = path.join(ROOT, 'appsync');            /* 模板资产目录 */
const OUT  = path.join(ROOT, 'family');             /* Pages 伺服目录（workflow 自提交） */
const FEED = path.join(ROOT, 'jd_cloud_feed.json'); /* 抓数产物（元/斤 口径） */
const ASSETS = ['manifest.json', 'sw.js', 'icon-192.png', 'icon-512.png', 'icon-180.png'];
const ALL = ['jd2611.html'].concat(ASSETS, ['index.html']);

function log(s) { console.log('[family] ' + s); }

/* 注入最新现货价到 SPOT_SEED（仅副本，模板不动）。
   口径换算：云端包 spot.today 是元/斤（如 4.44），SPOT_SEED 历史是元/500kg（如 4440）——×1000；
   日期换算：云端包 auto.date 是 YYYYMMDD（如 20260930），SPOT_SEED 键是 YYYY-MM-DD。
   与原 pages_sync.js 同一套正则/校验（值域 500~20000 元/500kg），区别仅注入源与换算。 */
function injectSpot(html) {
  let feed = null;
  try { feed = JSON.parse(fs.readFileSync(FEED, 'utf8')); } catch (e) { /* 无数据包照常组包 */ }
  const today = feed && feed.spot && +feed.spot.today;
  const rawDate = (feed && feed.spot && feed.spot.auto && feed.spot.auto.date) || '';
  if (!(today > 0)) { log('jd_cloud_feed.json 无现货数据，沿用模板种子'); return html; }
  const m = html.match(/const SPOT_SEED=(\[\[[\s\S]*?\]\])/);
  if (!m) { log('未找到 SPOT_SEED 字面量，跳过注入'); return html; }
  let seed;
  try { seed = JSON.parse(m[1]); } catch (e) { log('SPOT_SEED 解析失败，跳过注入'); return html; }
  const price = Math.round(today * 1000); /* 元/斤 → 元/500kg */
  const date = /^\d{8}$/.test(rawDate) ? (rawDate.slice(0, 4) + '-' + rawDate.slice(4, 6) + '-' + rawDate.slice(6, 8))
             : (/^\d{4}-\d{2}-\d{2}$/.test(rawDate) ? rawDate : '');
  if (!date || price < 500 || price > 20000) {
    log('现货数据异常(date=' + rawDate + ' price=' + price + ')，跳过注入'); return html;
  }
  const i = seed.findIndex(function (x) { return x[0] === date; });
  if (i >= 0) seed[i][1] = price; else seed.push([date, price]);
  const out = seed.slice(-400);
  log('现货注入 ' + date + ' = ' + price + ' 元/500kg（云端 ' + today + ' 元/斤 ×1000）');
  return html.replace(m[0], 'const SPOT_SEED=' + JSON.stringify(out));
}

/* 从现存 family/jd2611.html 提取已注入的 SPOT_SEED（v17.29 修复②）。
   机理：模板 appsync/ 从不含注入点，价格点只存在于输出文件——若某轮无有效现货
   （injectSpot 跳过注入）输出被模板重建，历史点即回退丢失（2026-10-07 事故：
   09-30 价格点被回退为 08-27）。组包前先把现存输出种子并回模板，无现货轮次也不再回退。 */
function loadExistingSeed() {
  try {
    const prev = fs.readFileSync(path.join(OUT, 'jd2611.html'), 'utf8');
    const m = prev.match(/const SPOT_SEED=(\[\[[\s\S]*?\]\])/);
    if (!m) return null;
    const seed = JSON.parse(m[1]);
    return (Array.isArray(seed) && seed.length) ? seed : null;
  } catch (e) { return null; }
}

function main() {
  let html = fs.readFileSync(path.join(SRC, 'jd2611.html'), 'utf8');
  const existing = loadExistingSeed();
  if (existing) {
    const tm = html.match(/const SPOT_SEED=(\[\[[\s\S]*?\]\])/);
    if (tm && tm[1] !== JSON.stringify(existing)) {
      html = html.replace(tm[0], 'const SPOT_SEED=' + JSON.stringify(existing));
      log('种子基底并回：现存输出 ' + existing.length + ' 点（模板自带 ' + JSON.parse(tm[1]).length + ' 点）');
    }
  }
  html = injectSpot(html);

  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'jd2611.html'), html);
  for (const f of ASSETS) fs.copyFileSync(path.join(SRC, f), path.join(OUT, f));
  /* 访问 /-/family/（不带文件名）时跳主页面，不 404 */
  fs.writeFileSync(path.join(OUT, 'index.html'),
    '<!doctype html><meta charset="utf-8"><title>鸡蛋JD2611</title>' +
    '<meta http-equiv="refresh" content="0;url=./jd2611.html">' +
    '<script>location.replace("./jd2611.html")</script>' +
    '<p style="font:16px sans-serif"><a href="./jd2611.html">进入 鸡蛋JD2611 交易系统</a></p>');

  /* 内容指纹（不含时间戳——内容不变则 diff 为空，workflow 跳过提交） */
  const h = crypto.createHash('sha256');
  for (const f of ALL) {
    h.update(f).update(crypto.createHash('sha256').update(fs.readFileSync(path.join(OUT, f))).digest('hex'));
  }
  fs.writeFileSync(path.join(OUT, '.build-stamp'), h.digest('hex') + '\n');
  log('组包完成 → family/（' + ALL.length + ' 个文件 + .build-stamp）');
}

main();
