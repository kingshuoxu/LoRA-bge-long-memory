// 把一帧亮度分成「软星云」和「格子噪点」。
// 软云的相邻像素只差几个亮度级。点阵、菱形格、竖条会让很多相邻像素跳变，平均梯度也高。
// 阈值由 nebula-pixels.test.mjs 里的合成图锁住，不看显卡名字。

export function classifyField(lumas, width, height) {
  const n = width * height;
  if (!n || !lumas || lumas.length < n || width < 4 || height < 4) {
    return { lattice: false, flip: 0, peak: 0, rough: 0, variance: 0, mean: 0 };
  }
  let sum = 0;
  let sum2 = 0;
  for (let i = 0; i < n; i += 1) {
    const v = lumas[i];
    sum += v;
    sum2 += v * v;
  }
  const mean = sum / n;
  const variance = Math.max(0, sum2 / n - mean * mean);

  let flips = 0;
  let roughSum = 0;
  let pairs = 0;
  for (let y = 0; y < height; y += 1) {
    const row = y * width;
    for (let x = 0; x < width - 1; x += 1) {
      const d = Math.abs(lumas[row + x] - lumas[row + x + 1]);
      roughSum += d;
      pairs += 1;
      if (d > 28) flips += 1;
    }
  }
  for (let y = 0; y < height - 1; y += 1) {
    const row = y * width;
    const next = (y + 1) * width;
    for (let x = 0; x < width; x += 1) {
      const d = Math.abs(lumas[row + x] - lumas[next + x]);
      roughSum += d;
      pairs += 1;
      if (d > 28) flips += 1;
    }
  }
  const flip = pairs ? flips / pairs : 0;
  const rough = pairs ? roughSum / pairs : 0;

  let peaks = 0;
  let samples = 0;
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      samples += 1;
      const c = lumas[y * width + x];
      const neigh = (
        lumas[y * width + x - 1]
        + lumas[y * width + x + 1]
        + lumas[(y - 1) * width + x]
        + lumas[(y + 1) * width + x]
      ) / 4;
      if (c > neigh + 36 && c > mean + 18) peaks += 1;
    }
  }
  const peak = samples ? peaks / samples : 0;
  const lattice = variance > 20 && rough > 11 && (flip > 0.08 || peak > 0.02);
  return { lattice, flip, peak, rough, variance, mean };
}
