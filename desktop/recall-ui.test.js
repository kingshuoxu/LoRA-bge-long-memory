const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function renderer(locale, advanced = false) {
  const banner = { hidden: false, dataset: {}, classList: { toggle(k, value) { this[k] = value; } } };
  const ctx = vm.createContext({ window: {}, localStorage: { getItem: () => locale }, document: { readyState: 'loading', addEventListener() {} }, state: { view: 'chat' }, $: () => banner, advancedOn: () => advanced });
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'ui/i18n.js'), 'utf8'), ctx);
  vm.runInContext('const t = (key, vars) => window.i18n.t(key, vars); const tx = value => value; function esc(value) { return String(value ?? "").replace(/[&<>"\x27]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","\x27":"&#39;"}[c])); }', ctx);
  const app = fs.readFileSync(path.join(__dirname, 'ui/app.js'), 'utf8');
  // Execute the production render functions, not a copied implementation.
  vm.runInContext(app.slice(app.indexOf('function recallTrace('), app.indexOf('function reducedMotion(')), ctx);
  return { ctx, banner };
}
for (const locale of ['zh-CN', 'en']) {
  for (const advanced of [false, true]) test(`${locale} confirmed memory renders correcting source, advanced=${advanced}`, () => {
    const { ctx, banner } = renderer(locale, advanced);
    const trace = { authority: 'confirmed_fact', fired: true, mounted: false, reason: 'confirmed_correction', matched_facts: [{ entity: 'Alex', statement: 'Alex lives in Starport.', source_conversations: [{ id: 'new', title: 'Correction <chat>' }], original_source_conversations: [{ title: 'Wrong old chat' }] }] };
    const label = ctx.chipLabel(trace);
    assert.match(label, /Starport/); assert.match(label, /Correction <chat>/); assert.doesNotMatch(label, /Wrong old chat|Memory not used|未调用记忆/);
    const html = ctx.recallChip({ id: 'm1', content: 'Starport.' }, { trace });
    assert.match(html, /Correction &lt;chat&gt;/); assert.doesNotMatch(html, /recall-chip idle/);
    assert.match(ctx.chipTitle(trace), locale === 'en' ? /no LoRA adapter mounted/ : /未挂载 LoRA/);
    ctx.showRecallBanner(trace); assert.equal(banner.dataset.live, '1'); assert.equal(banner.classList.idle, false); assert.match(banner.textContent, /Correction <chat>/);
    assert.equal(trace.mounted, false);
  });
  test(`${locale} ordinary unmounted and proposal remain idle`, () => {
    const { ctx, banner } = renderer(locale);
    for (const trace of [{ mounted: false }, { mounted: false, authority: 'confirmed_fact', fired: false }, { mounted: false, reason: 'correction_proposal' }]) {
      assert.equal(ctx.chipLabel(trace), locale === 'en' ? 'Memory not used' : '未调用记忆');
      assert.equal(ctx.chipTitle(trace), '');
      ctx.showRecallBanner(trace); assert.equal(banner.dataset.live, ''); assert.equal(banner.classList.idle, true);
    }
  });
}
