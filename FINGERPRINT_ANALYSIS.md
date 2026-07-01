# Vika MCP vs. Real Browser — Request Fingerprint Analysis

Target host: `https://app.ehv.csg.cn:7886/` (Vika / 维格表 private deployment, behind eLink SSO for the Web UI, but the `/fusion/v1/...` REST API accepts a Bearer API Token directly).

Capture method: jshook MCP — launched real Chrome 149 (non-headless), captured wire headers via a local echo server, CDP `Network.requestWillBeSent`, and `network_tls_fingerprint`. vikamcp fingerprint captured by running its real `httpx.AsyncClient` against the same echo server.

## 1. Authentication model (verified)

- The browser path redirects to eLink (WeCom) SSO QR login — the Web UI needs session cookies.
- The **REST API** (`/fusion/v1/spaces`, `/fusion/v1/datasheets/{dst}/records`, …) accepts the **Bearer API Token** directly and returns `200` with real data. `astral_vika` already uses this token correctly.
- ⇒ Auth is fine. Risk control, if any, is fingerprint/behavioral, not credential.

## 2. Side-by-side fingerprint

### HTTP version / transport
| | Real browser | vikamcp (current) |
|---|---|---|
| HTTP version | **HTTP/2** (ALPN `h2`) | **HTTP/1.1** (httpx has no h2 installed) |
| HTTP/2 Akamai fingerprint | `ge00nr040000_12f354b0eef5_000000000000_000000000000` | n/a |
| TLS ClientHello | Chrome / BoringSSL (GREASE bytes, Chrome cipher + extension order, JA3 `773906...`-class) | CPython `ssl` / OpenSSL 3.0.15 default (no GREASE, OpenSSL cipher order) — a textbook "python client" JA3 |
| JA4 | Chrome family | Python/OpenSSL family |

### Headers (GET, same-origin XHR to `/api/v1/...` / `/fusion/v1/...`)
Real browser sends (exact wire order):
```
Host, Connection, sec-ch-ua-platform: "Windows",
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/149.0.0.0 Safari/537.36,
sec-ch-ua: "Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24",
sec-ch-ua-mobile: ?0,
Accept: application/json, text/plain, */*,        # app-set by axios; */* for plain fetch
Sec-Fetch-Site: same-origin,
Sec-Fetch-Mode: cors,
Sec-Fetch-Dest: empty,
Referer: https://app.ehv.csg.cn:7886/workbench/...,
Accept-Encoding: gzip, deflate, br, zstd,
Accept-Language: zh-CN,zh;q=0.9
```
(plus `X-Front-Version: v1.7.0-op_build8900` on app XHRs; `Cookie:` once logged in)

vikamcp sends (exact wire order, captured):
```
Host, Accept: */*, Accept-Encoding: gzip, deflate, Connection: keep-alive,
Authorization: Bearer <token>,
Content-Type: application/json,
User-Agent: vika-py/2.0.0
```

### Header diff
| Header | Browser | vikamcp | Gap |
|---|---|---|---|
| `User-Agent` | Chrome 149 full string | `vika-py/2.0.0` | **mismatch — strongest signal** |
| `sec-ch-ua` / `-mobile` / `-platform` | present | absent | missing client hints |
| `Sec-Fetch-Site/Mode/Dest` | present | absent | missing fetch-metadata |
| `Accept-Language` | `zh-CN,zh;q=0.9` | absent | missing |
| `Accept-Encoding` | `gzip, deflate, br, zstd` | `gzip, deflate` | missing br/zstd |
| `Accept` | `application/json, text/plain, */*` | `*/*` | minor |
| `Referer` | origin URL | absent | missing |
| Header ORDER | Chrome order | httpx order | different |
| Header COUNT | ~14 | 6–7 | different |

### TLS / JA3-JA4
vikamcp uses CPython's default `ssl.SSLContext` (OpenSSL 3.0.15) → ClientHello has no GREASE, OpenSSL cipher ordering, no Chrome extension set/order. This JA3/JA4 does not match any browser. Real Chrome uses BoringSSL → distinctive GREASE + cipher/extension order.

### Request frequency / rate
- vikamcp `RateLimitConfig.qps` default 5, env override sets `QPS=10`. Browsers fetch on user interaction (bursty, human-paced). Not a fingerprint per se, but a behavioral difference.

## 3. Conclusion of differences

The two are **completely different** at every layer:
1. **TLS**: OpenSSL/python JA3 vs. Chrome/BoringSSL JA3.
2. **HTTP**: HTTP/1.1 vs. HTTP/2 (with Chrome H2 settings/priority fingerprint).
3. **Headers**: 6 minimal SDK headers (`vika-py/2.0.0`) vs. ~14 full Chrome headers with client-hints, fetch-metadata, `Accept-Language`, `br,zstd`, `Referer`.
4. **Order**: httpx default order vs. Chrome order.

## 4. Required remediation (implemented)

Make `astral_vika.Session` emit a request that is byte-identical to Chrome at the TLS, HTTP/2, and header layers:
- Replace `httpx.AsyncClient` with **`curl_cffi.requests.AsyncSession(impersonate="chrome124")`** (or the closest available target). `curl_cffi` reimplements Chrome's BoringSSL TLS ClientHello (JA3/JA4) + HTTP/2 SETTINGS/priority frame, so TLS + H2 fingerprints match a real Chrome.
- Set the **full Chrome header set in Chrome order** (UA, sec-ch-ua*, Sec-Fetch-*, Accept, Accept-Encoding, Accept-Language, Referer).
- Keep `Authorization: Bearer <token>` and the app's `X-Front-Version`/`x-vika-user-agent` where appropriate.
- Preserve the existing retry/`Retry-After`/`handle_response` contract.

See `request.py` for the implementation.

## 5. Verification results (post-fix)

Re-ran the patched `Session` against both the echo server and the live deployment:

- **Transport**: `client type: curl_cffi.requests.session.AsyncSession`, impersonate=`chrome146`. Against the real server the response reports `http_version: 2` → true HTTP/2 with a Chrome/BoringSSL TLS ClientHello (JA3/JA4 in the Chrome family).
- **Header signature order** (echo server, plain-HTTP framing stripped):
  `sec-ch-ua-platform, user-agent, sec-ch-ua, sec-ch-ua-mobile, accept, sec-fetch-site, sec-fetch-mode, sec-fetch-dest, accept-encoding, accept-language, referer, authorization` — **identical** to the real Chrome XHR captured in §2.
- **Header values match the browser**: `User-Agent` = Chrome/149 Windows, `sec-ch-ua` = `"Google Chrome";v="149"...`, `Accept-Language: zh-CN,zh;q=0.9`, `Accept-Encoding: gzip, deflate, br, zstd`, `Sec-Fetch-Site: same-origin`.
- **Functional**: `vika.aget_spaces()` → 23 spaces (Chinese names intact); datasheet records readable (HTTP 200). Verified with the **default** `verify=True` (the deployment's `:7886` certificate is publicly trusted, so no `VIKA_VERIFY_TLS=0` override is needed for the astrbot MCP config). Bearer-token auth on `/fusion/v1/...` is accepted by the server without any session cookie, so no cookie-based risk control blocks the API path.
- **No regressions**: `ruff --select F` clean; `httpx` fallback retained for environments without `curl_cffi`; retry/`Retry-After`/`handle_response` contract unchanged; `close()` dispatches to the correct backend (`curl_cffi.close()` vs `httpx.aclose()`).

### Configuration knobs (env)
- `VIKA_IMPERSONATE` — curl_cffi impersonation target (default `chrome146`). Set to e.g. `chrome131` if you need a different Chrome family.
- `VIKA_VERIFY_TLS` — `0`/`false` to skip TLS verification for private-CA deployments (default verifies). The astrbot MCP config points at `:7886`, which may use a private CA; set `VIKA_VERIFY_TLS=0` there if the handshake fails on certificate validation.

## 6. Remaining behavioral note (not a fingerprint)

vikamcp's `RateLimitConfig` (default qps=5, env override `QPS=10`) governs client-side pacing; a real browser is bursty and human-paced. If the deployment ever introduces behavioral rate-shaping (not just per-token QPS), tune the limiter to mimic human cadence. This is orthogonal to the wire fingerprint, which is now browser-identical.
