# Setup

[← README](../README.md) · **English** · [Русский](SETUP.ru.md)

## Configuration

The setup container creates two private files in the project folder:

| File | Purpose |
| --- | --- |
| `.env` | Player address and a generated session encryption key |
| `oauth_apps.json` | Optional Shikimori and MAL application credentials |

Existing files are preserved. Edit `.env` if you change the player address. Recreate the app container after changing settings.

On Linux, the setup container uses UID/GID 1000 by default. If your account differs, run:

```sh
LOCAL_UID=$(id -u) LOCAL_GID=$(id -g) docker compose -f compose.setup.yaml run --rm setup http://127.0.0.1:8765
```

For an existing installation, keep its `.env` and `oauth_apps.json`; there is no need to generate a new key.

## OAuth

List integrations are optional. Register each service you want to use:

| Service | Application registration | Key in `oauth_apps.json` | Redirect path |
| --- | --- | --- | --- |
| Shikimori.io | [OAuth applications](https://shikimori.io/oauth/applications) | `one` | `/shiki/callback` |
| Shikimori RIP | [OAuth applications](https://shikimori.rip/oauth/applications) | `rip` | `/shiki/callback` |
| MyAnimeList | [API configuration](https://myanimelist.net/apiconfig) | `mal` | `/mal/callback` |

The redirect URL is your player address plus the path above, for example `http://127.0.0.1:8765/mal/callback`. For Shikimori, enable the `user_rates` permission. For MAL, select a Web application.

Fill in `client_id` and `client_secret` in the private `oauth_apps.json` created by `tools/init_config.py`, then recreate the app container. The internal key `one` represents shikimori.io. Supported RIP hosts include `shikimori.rip`, `shikirip.top` and `shikimori.net`.

Connect the service from the account menu. In the player, select the season's list entry and the connected services that should receive updates. Automatic progress updates preserve personal ratings and never reduce watched episode counts; manual Save applies the values displayed in the form. Lists are not automatically merged.

## Remote access over HTTPS

The app serves HTTP on `127.0.0.1:8765`. HTTPS is provided by a reverse proxy on the host: Caddy, Nginx, an existing proxy, or Tailscale Serve. The Docker profile support this. Use a dedicated hostname at the site root, such as `https://player.example.com`; hosting under `/player/` is not supported.

### Your domain and HTTPS

**1. Prepare the domain.** Point its DNS record at the server. Public hosting needs incoming connectivity; on a home connection this may require port forwarding and a public IP. For private LAN hosting, use internal DNS and a certificate trusted by your devices. You do not need Tailscale.

**2. Set the public address.** For a new installation:

```sh
docker compose -f compose.setup.yaml run --rm setup https://player.example.com
```

For an existing installation, edit this line in `.env` instead; the setup command preserves existing files:

```dotenv
CRUNCHY_LOCAL_PUBLIC_ORIGIN=https://player.example.com
```

Keep the session encryption key. Use the exact browser-facing origin, including a nonstandard port if needed, with no path or trailing slash.

**3. Set up a proxy.** The examples below assume the proxy runs directly on the same host as Docker. Choose one.

#### Caddy: automatic certificate

[Install Caddy](https://caddyserver.com/docs/install), then add this to its Caddyfile:

```caddyfile
player.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

Reload Caddy through your host's service manager. For automatic public certificates, DNS must point to the server and the required ACME challenge ports must be reachable; the standard setup uses ports 80 and 443. Caddy handles certificate renewal. See [automatic HTTPS](https://caddyserver.com/docs/automatic-https).

For your own certificate, add a `tls` line inside the same block:

```caddyfile
    tls /path/to/fullchain.pem /path/to/privkey.pem
```

The certificate must cover your domain, include the needed chain, and be trusted by every viewing device. Renew a supplied certificate yourself. For private CA certificates, install the CA on the devices; dismissing a certificate warning is not a reliable DRM setup.

#### Nginx: your own certificate

With Nginx installed, add the following server blocks to its HTTP configuration and replace the domain and certificate paths:

```nginx
server {
    listen 80;
    server_name player.example.com;
    return 301 https://player.example.com$request_uri;
}

server {
    listen 443 ssl;
    server_name player.example.com;
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 4m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering off;
        proxy_buffer_size 32k;
        proxy_buffers 8 32k;
        proxy_cache off;
    }
}
```

On Linux, check with `sudo nginx -t`, then reload with `sudo systemctl reload nginx`. Supply a valid certificate and its renewal mechanism; Nginx does not issue one from this configuration. See the official [HTTPS guide](https://nginx.org/en/docs/http/configuring_https_servers.html) and [proxy reference](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

For another proxy, preserve `Host`, set `X-Forwarded-Proto: https`, forward all paths and query parameters, and disable caching of authenticated responses. The app must remain reachable only through the proxy or localhost. In a separate proxy container, `127.0.0.1` refers to that container: configure a shared network or host connection instead; do not copy the upstream address above unchanged.

**4. Start or recreate the app.**

```sh
docker compose up -d --build --force-recreate app
```

**5. Update sign-in and verify.**

- Register `https://player.example.com/shiki/callback` and/or `https://player.example.com/mal/callback` in the corresponding OAuth apps.
- If using the Chromium extension or Tampermonkey, [configure it for the domain](#crunchyroll-sign-in), rebuild the app, and reinstall the updated extension/script. The distributed versions allow localhost by default.
- Open the HTTPS URL without certificate warnings, sign in, and test playback on your target device.

There is no general site-access account system. If the domain is reachable from the internet, restrict access at the reverse proxy, such as with authentication or an IP allowlist. Keep `.env`, OAuth secrets and certificate private keys outside public files.

## HTTPS and Tailscale

Install and connect Tailscale on the server and on each device that needs access. With the player running:

```sh
sudo tailscale serve --bg http://127.0.0.1:8765
```

Use the HTTPS address returned by Tailscale. Set it as `CRUNCHY_LOCAL_PUBLIC_ORIGIN` in `.env`, update the OAuth redirect URLs and recreate the app container.

The Docker profile binds to localhost. Tailscale Serve provides access to your tailnet; it does not publish the player to the open internet. Plain HTTP over a LAN IP is unsuitable for DRM playback.

## Crunchyroll sign-in

Enter your email and password in the player. The server submits them to Crunchyroll through its temporary browser. If additional verification is required, open the verification window offered by the player.

Desktop users can sign in on the official Crunchyroll site with either the Chromium extension or the Tampermonkey userscript (Firefox and compatible Chromium browsers). Importing `cookies.txt` is also available.

For Tampermonkey, install the manager from [its official website](https://www.tampermonkey.net/), then choose **Install Tampermonkey script** in the player's sign-in dialog. Use Tampermonkey Beta for HttpOnly access, as required by its documentation. In the manager’s global **Settings**, select **Config mode → Advanced**, then **Security → Allow scripts to access cookies → All**. Refresh the player and use its sign-in button. The script reads only `etp_rt`, sends it to the configured player, and does not store sessions in userscript storage. It requires no separate Mozilla signing.

To configure the extension and userscript for your server:

```sh
docker compose -f compose.setup.yaml run --rm --entrypoint python setup tools/configure_extension.py https://player.example.com
```

Install the unpacked extension through the browser's developer mode. Rebuild the app container after changing the extension configuration. Standard mobile Chrome does not support this extension; use the player's sign-in form.

## Maintenance

For the application:

```sh
docker compose logs --tail=100 app
docker compose up -d --build --force-recreate app
docker compose down
```

To apply downloaded source updates, run the rebuild command above. `down` stops and removes containers; it keeps settings and the catalog volume.

The public catalog refreshes on startup and daily. Failed updates preserve the last working version. Docker keeps it in the `catalog-data` volume; `down -v` deletes that cache. Change the interval in `.env` with `CRUNCHY_LOCAL_CATALOG_INTERVAL` (seconds, 3600–604800; default 86400).

| Problem | Check |
| --- | --- |
| ShakaError 6020 | Use localhost or HTTPS, with Chrome/Chromium (Widevine) or Safari on macOS (FairPlay). |
| Crunchyroll HTTP 420 | Stop playback in other tabs. After an interrupted session, wait a few minutes for Crunchyroll to release it, then retry. |
| OAuth fails | Match the redirect URL and `CRUNCHY_LOCAL_PUBLIC_ORIGIN` exactly. |
| Sign-in needs verification | Use the verification window; upstream protection may reject server browsers. |
| Anime details are missing | A MAL/Shikimori match or upstream data may be unavailable; playback remains accessible. |

## Private files

Never publish `.env`, `oauth_apps.json`, `.local/`, browser profiles or logs. Changing the encryption key invalidates existing account cookies. The server operator can access credentials while requests are being processed; browser cookies do not remove that trust requirement.
