// Camera distance. Smaller is closer. The far limit has to be at least the
// opening frame: a portrait phone with several experts frames around 200,
// and the old hard cap of 90 left the user stuck inside the cloud.

export const NEAR_ZOOM = 6;

export function farZoom(homeDistance) {
  const home = Number(homeDistance);
  if (!Number.isFinite(home) || home <= NEAR_ZOOM) return 90;
  return Math.max(home, 90);
}

export function clampZoomDistance(distance, homeDistance) {
  const far = farZoom(homeDistance);
  const value = Number(distance);
  if (!Number.isFinite(value)) return far;
  return Math.min(far, Math.max(NEAR_ZOOM, value));
}

// Sprites are sized in pixels, so they do not shrink when the camera pulls back.
// At the opening frame a whole expert is only a few dozen pixels across and the
// sprites pile up into a white core. Close in, the same sprites should stay as they are.
export const SPRITE_REF_DISTANCE = 48;

export function framingAmount(distance, homeDistance, refDistance = SPRITE_REF_DISTANCE) {
  const dist = Number(distance);
  const ref = Number(refDistance);
  if (!Number.isFinite(dist) || dist < 1 || !Number.isFinite(ref) || ref < 1) return 0;
  const home = Number(homeDistance);
  const far = Number.isFinite(home) && home > ref + 1 ? home : Math.max(dist, ref * 4);
  return Math.min(1, Math.max(0, (dist - ref) / Math.max(1, far - ref)));
}

function packed(distance, homeDistance, refDistance) {
  const t = framingAmount(distance, homeDistance, refDistance);
  // Square it so a mid zoom barely changes and only the opening frame packs down.
  return t * t;
}

export function spriteFit(distance, homeDistance, refDistance = SPRITE_REF_DISTANCE) {
  const u = packed(distance, homeDistance, refDistance);
  return {
    scale: 1 - u * 0.38,
    exposure: 1 - u * 0.42,
  };
}

// Bright core samples are the last ~14% of the buffer. The opening frame drops
// them and keeps the colored body. A mid zoom (u near 0) keeps every sample.
export function particleKeep(distance, homeDistance, refDistance = SPRITE_REF_DISTANCE) {
  const u = packed(distance, homeDistance, refDistance);
  return 1 - u * 0.22;
}

// Fact stars draw a white core plus diffraction spikes. Those spikes are what
// blow out when dozens of stars sit on a cloud the size of a thumbnail.
export function starFit(distance, homeDistance, refDistance = SPRITE_REF_DISTANCE) {
  const u = packed(distance, homeDistance, refDistance);
  return {
    scale: 1 - u * 0.5,
    exposure: 1 - u * 0.88,
  };
}
