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
