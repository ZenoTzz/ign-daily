# RSS Network Fallback

国内服务器访问 IGN 和 FeedBurner 偶尔会超时。网站和 API 可以继续放在国内，
但 RSS 抓取建议准备一个海外 Worker 作为兜底。

## How It Works

`scripts/ign_rss_incremental.py` 会先直连 RSS。直连失败时，如果 `.env` 里配置了
`IGN_DAILY_RSS_PROXY_URL`，脚本会自动通过代理再试一次。

`.env` 示例：

```bash
IGN_DAILY_RSS_PROXY_URL=https://your-worker.example.workers.dev/rss?url={url}
IGN_DAILY_RSS_TIMEOUT=10
```

`{url}` 会被替换成编码后的 RSS 地址。

## Cloudflare Worker Example

```js
export default {
  async fetch(request) {
    const { searchParams } = new URL(request.url);
    const raw = searchParams.get("url");
    if (!raw) {
      return new Response("Missing url", { status: 400 });
    }

    let upstream;
    try {
      upstream = new URL(raw);
    } catch {
      return new Response("Invalid url", { status: 400 });
    }

    const allowedHosts = new Set([
      "www.ign.com",
      "feeds.feedburner.com",
    ]);
    if (!allowedHosts.has(upstream.hostname)) {
      return new Response("Host not allowed", { status: 403 });
    }

    const response = await fetch(upstream.toString(), {
      headers: {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
      },
      cf: { cacheTtl: 120, cacheEverything: true },
    });

    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "application/xml; charset=utf-8",
        "Cache-Control": "public, max-age=120",
      },
    });
  },
};
```

## Server Test

After setting `.env`, run:

```bash
cd /srv/ign-daily
/srv/ign-daily-venv/bin/python scripts/ign_rss_incremental.py --lookback-days 2
```

If direct access fails but the Worker succeeds, the logs will show the RSS URL
with `via https://...`.
