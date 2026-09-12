// Vercel serverless proxy — keeps GOOGLE_PLACES_API_KEY out of the browser.
export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  const key = process.env.GOOGLE_PLACES_API_KEY;
  if (!key) return res.status(503).json({ error: 'GOOGLE_PLACES_API_KEY not configured' });

  const { latitude, longitude, radius = 350 } = req.body || {};
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return res.status(400).json({ error: 'bad request' });
  }
  const r = await fetch('https://places.googleapis.com/v1/places:searchNearby', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Goog-Api-Key': key,
      'X-Goog-FieldMask':
        'places.displayName,places.location,places.primaryType,places.types,places.rating,places.userRatingCount,places.businessStatus',
    },
    body: JSON.stringify({
      includedTypes: ['restaurant', 'cafe', 'bakery', 'bar', 'meal_takeaway', 'ice_cream_shop'],
      maxResultCount: 20,
      locationRestriction: {
        circle: { center: { latitude, longitude }, radius: Math.min(1500, Math.max(50, radius)) },
      },
    }),
  });
  const j = await r.json().catch(() => ({ error: 'upstream parse error' }));
  res.status(r.status).json(j);
}
