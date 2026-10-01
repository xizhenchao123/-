/* v17.28b: 家人版组包脚本（云端版）——在 GitHub Actions 内运行
   逻辑移植自本地 pages_sync.js，但无本地依赖：
   - 现货注入源改为仓库根 jd_cloud_feed.json（v17.28 云端抓取产物），不再请求 localhost:8080
   - 部署凭据全部来自环境变量（Actions Secrets），不读 pages_config.json
   - 无哈希跳过（本地 pages_state.json 在 Actions 是一次性环境）→ 每次全量部署（免费额度足够）
   用法: node scripts/cloud_pages_deploy.js */
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');          // 仓库根
const APP = path.join(ROOT, 'appsync');              // 家人版资产源目录
const BUNDLE = path.join(ROOT, 'pages_bundle');      // 组包输出（部署目录）
const ASSETS = ['manifest.json', 'sw.js', 'icon-192.png', 'icon-512.png', 'icon-180.png'];

function log(s) { console.log('[cloud-pages] ' + s); }

/* 把最新现货价注入家人版副本的 SPOT_SEED（种子即爸妈设备上的现货来源） */
function injectSpot(html, feed) {
  if (!feed || !(+feed.spot.today > 0)) { log('无现货数据，沿用种子末值'); return html; }
  const d = String(feed.spot.auto && feed.spot.auto.date || '');
  const date = d.length === 8 ? d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6, 8) : null;
  if (!date) { log('现货数据无日期，沿用种子末值'); return html; }
  const m = html.match(/const SPOT_SEED=(\[\[[\s\S]*?\]\])/);
  if (!m) { log('未找到SPOT_SEED字面量，跳过注入'); return html; }
  const seed = JSON.parse(m[1]);
  const price = +feed.spot.today;                    /* 元/500kg，与页面 autoSpot 同口径 */
  const i = seed.findIndex(x => x[0] === date);
  if (i >= 0) seed[i][1] = price; else seed.push([date, price]);
  const out = seed.slice(-400);
  log('现货注入 ' + date + ' = ' + price);
  return html.replace(m[0], 'const SPOT_SEED=' + JSON.stringify(out));
}

/* 组包：家人版主页面 + PWA 资产 + 根路径跳转兜底 */
function buildBundle(html) {
  fs.rmSync(BUNDLE, { recursive: true, force: true });
  fs.mkdirSync(BUNDLE, { recursive: true });
  fs.writeFileSync(path.join(BUNDLE, 'jd2611.html'), html);
  for (const f of ASSETS) fs.copyFileSync(path.join(APP, f), path.join(BUNDLE, f));
  fs.writeFileSync(path.join(BUNDLE, 'index.html'),
    '<!doctype html><meta charset="utf-8"><title>鸡蛋JD2611</title>' +
    '<meta http-equiv="refresh" content="0;url=./jd2611.html">' +
    '<script>location.replace("./jd2611.html")</script>' +
    '<p style="font:16px sans-serif"><a href="./jd2611.html">进入 鸡蛋JD2611 交易系统</a></p>');
}

function wranglerJs() {
  /* Actions 上直接 npx wrangler 即可；此函数保留兜底逻辑（找缓存 wrangler.js） */
  const home = process.env.HOME || process.env.USERPROFILE;
  const bases = [path.join(home, '.npm', '_npx'), path.join(home, 'AppData', 'Local', 'npm-cache', '_npx')];
  for (const b of bases) {
    try {
      for (const d of fs.readdirSync(b)) {
        const w = path.join(b, d, 'node_modules', 'wrangler', 'bin', 'wrangler.js');
        if (fs.existsSync(w)) return w;
      }
    } catch (e) { }
  }
  return null;
}

function run(args) {
  const env = {
    CLOUDFLARE_API_TOKEN: process.env.CF_API_TOKEN || '',
    CLOUDFLARE_ACCOUNT_ID: process.env.CF_ACCOUNT_ID || '',
  };
  const wjs = wranglerJs();
  const r = wjs
    ? spawnSync(process.execPath, [wjs].concat(args), { cwd: ROOT, env, encoding: 'utf8', timeout: 300000 })
    : spawnSync('npx', ['-y', 'wrangler@latest'].concat(args), { cwd: ROOT, env, encoding: 'utf8', timeout: 300000, shell: process.platform === 'win32' });
  return { status: r.status, out: (r.stdout || '') + (r.stderr || '') };
}

const PROJECT = process.env.CF_PROJECT || 'jd2611';

function main() {
  if (!process.env.CF_API_TOKEN || !process.env.CF_ACCOUNT_ID) {
    log('缺少 CF_API_TOKEN / CF_ACCOUNT_ID 环境变量（应在 Actions Secrets 配置）');
    process.exit(1);
  }
  const feedPath = path.join(ROOT, 'jd_cloud_feed.json');
  let feed = null;
  try { feed = JSON.parse(fs.readFileSync(feedPath, 'utf8')); } catch (e) { log('jd_cloud_feed.json 不可读：' + e.message); }

  let html = fs.readFileSync(path.join(APP, 'jd2611.html'), 'utf8');
  html = injectSpot(html, feed);
  buildBundle(html);
  log('组包完成：' + fs.readdirSync(BUNDLE).join(', '));

  log('部署到 Cloudflare Pages (project=' + PROJECT + ') ...');
  let r = run(['pages', 'deploy', 'pages_bundle', '--project-name', PROJECT, '--branch', 'main']);
  if (r.status !== 0 && /not found|10004|failed to find|unknown project|does not exist/i.test(r.out)) {
    log('项目不存在，先创建 ...');
    const rc = run(['pages', 'project', 'create', PROJECT, '--production-branch', 'main']);
    log('创建结果: ' + rc.out.split('\n').filter(x => /creat|succ|error|fail/i.test(x)).join(' | ').slice(0, 200));
    r = run(['pages', 'deploy', 'pages_bundle', '--project-name', PROJECT, '--branch', 'main']);
  }
  if (r.status !== 0) {
    console.log(r.out.split('\n').filter(x => x.trim()).slice(-15).join('\n'));
    log('部署失败——检查 Secrets CF_API_TOKEN / CF_ACCOUNT_ID 权限（需 Account | Cloudflare Pages | Edit）');
    process.exit(1);
  }
  const urls = [...new Set((r.out.match(/https:\/\/[a-z0-9-]+\.pages\.dev/gi) || []))];
  const prod = urls.find(u => u.replace(/^https:\/\//, '').startsWith(PROJECT + '.'));
  log('部署成功! 家人链接: ' + ((prod || urls[0] || ('https://' + PROJECT + '.pages.dev')) + '/jd2611.html'));
}

main();
