// Vercel serverless proxy — keeps GEMINI_API_KEY out of the browser.
export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  const key = process.env.GEMINI_API_KEY;
  if (!key) return res.status(503).json({ error: 'GEMINI_API_KEY not configured' });

  const { model = 'gemini-3.6-flash', body } = req.body || {};
  if (!/^gemini-[\w.-]{1,40}$/.test(model) || !body || typeof body !== 'object') {
    return res.status(400).json({ error: 'bad request' });
  }
  const r = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
  );
  const j = await r.json().catch(() => ({ error: 'upstream parse error' }));
  res.status(r.status).json(j);
}
