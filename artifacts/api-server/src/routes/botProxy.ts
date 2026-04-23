import { Router, type IRouter, type Request, type Response } from "express";

const router: IRouter = Router();
const BOT_BASE = "http://127.0.0.1:5000";

async function forward(req: Request, res: Response): Promise<void> {
  const subPath = req.path;
  const targetUrl = `${BOT_BASE}${subPath}`;
  try {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    for (const [k, v] of Object.entries(req.headers)) {
      const lk = k.toLowerCase();
      if (lk.startsWith("x-") && typeof v === "string") headers[k] = v;
    }
    const init: RequestInit = { method: req.method, headers };
    if (req.method !== "GET" && req.method !== "HEAD") {
      init.body = JSON.stringify(req.body || {});
    }
    const upstream = await fetch(targetUrl, init);
    const text = await upstream.text();
    res.status(upstream.status);
    const ct = upstream.headers.get("content-type");
    if (ct) res.setHeader("Content-Type", ct);
    res.send(text);
  } catch (err) {
    res.status(502).json({ error: "bot_unreachable", detail: String(err) });
  }
}

router.all(/.*/, forward);

export default router;
