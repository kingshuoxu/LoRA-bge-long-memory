import assert from "node:assert/strict";
import { classifyField } from "./nebula-pixels.js";
import { clampZoomDistance, farZoom, particleKeep, spriteFit, starFit } from "./nebula-zoom.js";

function field(width, height, paint) {
  const lumas = new Float32Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      lumas[y * width + x] = paint(x, y, width, height);
    }
  }
  return lumas;
}

function report(name, lumas, width, height) {
  const got = classifyField(lumas, width, height);
  console.log(
    `${name} lattice=${got.lattice} flip=${got.flip.toFixed(3)} peak=${got.peak.toFixed(3)} rough=${got.rough.toFixed(2)} var=${got.variance.toFixed(1)} mean=${got.mean.toFixed(1)}`,
  );
  return got;
}

const w = 96;
const h = 72;

const checker = field(w, h, (x, y) => ((x + y) % 2 === 0 ? 220 : 25));
const vivo = field(w, h, (x, y) => {
  const brown = 55 + (y / h) * 70 + (x / w) * 25;
  const cell = 4;
  const gx = x % cell;
  const gy = y % cell;
  const diamond = Math.abs(gx - 1) + Math.abs(gy - 1);
  if (diamond === 0) return 235;
  if (diamond === 1) return Math.min(255, brown + 90);
  if ((x * 2 + y) % 9 === 0) return Math.min(255, brown + 55);
  if (x % 7 === 0) return Math.min(255, brown + 35);
  return brown;
});
const stripes = field(w, h, (x, y) => (x % 2 === 0 ? 30 + y * 0.4 : 160));
const soft = field(w, h, (x, y) => {
  let v = 10;
  const blobs = [
    [28, 26, 18, 78],
    [68, 34, 16, 64],
    [48, 54, 20, 52],
    [40, 30, 8, 40],
  ];
  blobs.forEach(([cx, cy, s, amp]) => {
    const dx = x - cx;
    const dy = y - cy;
    v += amp * Math.exp(-(dx * dx + dy * dy) / (s * s));
  });
  [[18, 16], [74, 28], [52, 48], [30, 60]].forEach(([sx, sy]) => {
    const r = Math.hypot(x - sx, y - sy);
    v += 150 * Math.exp(-r * r * 1.6);
  });
  return Math.min(255, v);
});
const galaxy = field(w, h, (x, y) => {
  const nx = x / w;
  const ny = y / h;
  let v = 8 + ny * 14;
  const bandY = ny - 0.48 - (nx - 0.5) * 0.35;
  v += 70 * Math.exp(-(bandY * bandY) / 0.012);
  v += 28 * Math.exp(-((nx - 0.3) ** 2 + (ny - 0.4) ** 2) / 0.08);
  [[12, 14], [30, 22], [70, 18], [80, 50], [22, 58], [60, 40]].forEach(([sx, sy]) => {
    const r = Math.hypot(x - sx, y - sy);
    v += 160 * Math.exp(-r * r * 2.4);
  });
  return Math.min(255, v);
});
const sparseStars = field(w, h, (x, y) => {
  let v = 6;
  [[8, 10], [40, 20], [70, 55], [20, 60], [84, 16], [55, 36], [33, 48], [62, 12]].forEach(([sx, sy]) => {
    const r = Math.hypot(x - sx, y - sy);
    v += 180 * Math.exp(-r * r * 2.8);
  });
  return Math.min(255, v);
});
const flat = field(w, h, () => 9);
const smoothBrown = field(w, h, (x, y) => 40 + (y / h) * 50 + (x / w) * 20);
const tightParticles = field(w, h, (x, y) => {
  let v = 8;
  for (let i = 0; i < 40; i += 1) {
    const cx = 20 + (i * 37) % 58;
    const cy = 16 + (i * 19) % 42;
    const dx = x - cx;
    const dy = y - cy;
    v += 36 * Math.exp(-(dx * dx + dy * dy) / 16);
  }
  return Math.min(255, v);
});

const cases = [
  ["checker", checker, true],
  ["vivo-lattice", vivo, true],
  ["stripes", stripes, true],
  ["soft-nebula", soft, false],
  ["galaxy", galaxy, false],
  ["sparse-stars", sparseStars, false],
  ["flat-dark", flat, false],
  ["smooth-brown", smoothBrown, false],
  ["tight-particles", tightParticles, false],
];

let failed = 0;
cases.forEach(([name, lumas, want]) => {
  const got = report(name, lumas, w, h);
  if (got.lattice !== want) {
    console.error(`FAIL ${name}: expected lattice=${want}`);
    failed += 1;
  }
});

assert.equal(failed, 0, "lattice classifier disagreed with the fixtures");
const again = classifyField(vivo, w, h);
assert.equal(again.lattice, true);
assert.ok(again.flip > 0.08 || again.peak > 0.02);
assert.ok(again.rough > 11);
const softReport = classifyField(soft, w, h);
assert.equal(softReport.lattice, false);
assert.ok(softReport.rough < 11, `soft nebula rough ${softReport.rough} is too close to the lattice cut`);
console.log("nebula pixel classifier ok");

assert.equal(farZoom(244), 244);
assert.equal(clampZoomDistance(400, 244), 244);
assert.equal(clampZoomDistance(90, 244), 90);
assert.equal(clampZoomDistance(22, 244), 22);
assert.equal(clampZoomDistance(2, 244), 6);
assert.equal(clampZoomDistance(100, 70), 90);
assert.equal(clampZoomDistance(400, 180), 180);
console.log("nebula zoom clamp ok");

const homeFit = spriteFit(244, 244);
const midFit = spriteFit(76, 244);
const closeFit = spriteFit(28, 244);
const homeStars = starFit(244, 244);
assert.ok(homeFit.scale > 0.58 && homeFit.scale < 0.66, `home scale ${homeFit.scale}`);
assert.ok(homeFit.exposure > 0.54 && homeFit.exposure < 0.62, `home exposure ${homeFit.exposure}`);
assert.ok(particleKeep(244, 244) > 0.74 && particleKeep(244, 244) < 0.82, `keep ${particleKeep(244, 244)}`);
assert.ok(homeStars.exposure > 0.08 && homeStars.exposure < 0.16, `star exposure ${homeStars.exposure}`);
assert.ok(homeStars.scale > 0.45 && homeStars.scale < 0.55, `star scale ${homeStars.scale}`);
assert.ok(midFit.scale > 0.96, `mid scale ${midFit.scale}`);
assert.ok(midFit.exposure > 0.96, `mid exposure ${midFit.exposure}`);
assert.ok(particleKeep(76, 244) > 0.96);
assert.ok(starFit(76, 244).exposure > 0.96);
assert.equal(closeFit.scale, 1);
assert.equal(closeFit.exposure, 1);
assert.equal(particleKeep(28, 244), 1);
assert.equal(starFit(28, 244).exposure, 1);
assert.equal(starFit(28, 244).scale, 1);
console.log("nebula sprite fit ok");
