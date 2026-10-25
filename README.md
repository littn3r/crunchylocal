# Crunchy Local

**Your own Crunchyroll player — in the browser, with your anime lists kept in sync.**

**English** · [Русский](README.ru.md)

Crunchy Local is a small self-hosted web player. You run it in Docker on your computer or a home server, open it in any browser, and watch — no desktop app to install.

One place to watch, read about a show and tick off episodes on Shikimori or MyAnimeList — without juggling tabs.

## What it does

- 🔎 **Catalog** — browse, search and filter the whole Crunchyroll library.
- 🎬 **Player** — pick the audio language, get properly styled subtitles, and tweak dialogue size and position to taste.
- ⏯️ **Picks up where you left off** — resume playback, go fullscreen or use the mini player.
- 📋 **List sync** — connect Shikimori and/or MyAnimeList, and watched episodes, scores and statuses update for you.
- 📖 **Show pages** — descriptions, studios, genres, ratings and characters.
- 🌐 **English and Russian** — the first time you open it, the interface matches your browser language.

The catalog refreshes itself once a day.

## What you need

- **A Crunchyroll account with an active subscription.** The player doesn't unlock anything — the show has to be available to your account in the region you're using.
- **Docker with Compose:**

| Server runs on | Install |
| --- | --- |
| Windows | Docker Desktop (Linux containers) |
| macOS | Docker Desktop |
| Linux | Docker Engine + Compose plugin |

## Supported browsers

| Device | Browser |
| --- | --- |
| Computer | Chrome/Chromium, or Firefox with DRM enabled |
| Mac | Safari ✅ tested |
| iPhone | Safari ✅ tested on a real device |
| Android | Any browser with Widevine ✅ tested |

Playback uses Widevine where available and FairPlay in Safari. iPad hasn't been tested yet — if you try it, feedback is very welcome.

## Quick start

**1. Get the code.** Clone the repo, or click **Code → Download ZIP** and extract it. Open a terminal in the project folder, and make sure Docker Desktop is running if you use it.

**2. Generate your settings.**

```sh
docker compose -f compose.setup.yaml run --rm setup http://127.0.0.1:8765
```

This creates `.env` and `oauth_apps.json`. It never overwrites files that already exist, and you don't need Python or Node.js on your machine — everything runs inside Docker.

**3. Start the player.**

```sh
docker compose up -d --build
```

The first build downloads everything it needs, so give it a few minutes.

**4. Open [http://127.0.0.1:8765](http://127.0.0.1:8765)** and sign in to Crunchyroll. Shikimori and MAL are optional — connect them whenever you like.

> On Linux, if your user ID isn't 1000, see the [configuration notes](docs/SETUP.md#configuration).

## Watching on other devices

To watch from your phone, TV box or another computer, the browser needs **HTTPS with a trusted certificate** — DRM won't play over plain HTTP on a network address. Pick whichever setup suits you:

| Option | Good for |
| --- | --- |
| [Your own domain + Caddy or Nginx](docs/SETUP.md#your-domain-and-https) | Your own server, automatic or custom certificates; no Tailscale needed |
| [Tailscale Serve](docs/SETUP.md#https-and-tailscale) | Private access from your own devices on a Tailscale network |

### With your own domain

1. Point a domain such as `player.example.com` at your server. For a home server, open incoming access on your router if you want it reachable from the internet.
2. In `.env`, set `CRUNCHY_LOCAL_PUBLIC_ORIGIN=https://player.example.com`.
3. Run an HTTPS reverse proxy on the same machine: `https://player.example.com` → `http://127.0.0.1:8765`.
4. Recreate the app: `docker compose up -d --build --force-recreate app`.
5. If Shikimori/MAL are connected, update their redirect URLs. Then open the site on your device.

[Ready-to-copy Caddy, Nginx and custom-certificate examples →](docs/SETUP.md#your-domain-and-https)

### With Tailscale

Install Tailscale on the server and on the devices you watch from, put them on the same tailnet and turn on Tailscale Serve. Then open the HTTPS address it gives you — [step-by-step guide](docs/SETUP.md#https-and-tailscale).

A few things worth knowing:

- The server and Docker need to stay on while you watch.
- `127.0.0.1` always means *the device the browser is running on*. From another device, use the server's HTTPS address instead.
- HTTPS encrypts the connection, but it doesn't decide **who** can open the site. If you expose the player to the internet, put access control (password, IP allowlist) on your proxy.

## Where to go next

| I want to… | Guide |
| --- | --- |
| Connect Shikimori or MAL | [Account setup](docs/SETUP.md#oauth) |
| Watch from other devices | [Domain or Tailscale](docs/SETUP.md#remote-access-over-https) |
| Stop, update or troubleshoot | [Maintenance](docs/SETUP.md#maintenance) |

On desktop you can also sign in through a Chromium extension or a **Tampermonkey Beta userscript for Firefox**. Both use the official Crunchyroll sign-in page — see [Crunchyroll sign-in](docs/SETUP.md#crunchyroll-sign-in).

## How it works

Docker runs two things: the website itself, and a hidden Chromium browser that handles the Crunchyroll sign-in. The video plays in **your** browser, not on the server.

Your account sessions live in encrypted browser cookies; the server only holds credentials and tokens in memory while it's working with them. OAuth app secrets and the encryption key stay in private server config. Watch progress and preferences are stored per browser.

## Disclaimer

This is an **unofficial, personal-use project**. It isn't affiliated with, endorsed by or connected to Crunchyroll, Sony, Shikimori or MyAnimeList. It doesn't bypass DRM or subscriptions — you watch what your own account already gives you access to. Crunchyroll can change things on their side at any time, which may break sign-in or playback until the project catches up.

## Credits


| Project | Used for |
| --- | --- |
| [Crunchyroll Advanced Search](https://github.com/af-chacon/CrunchyRollAdvancedSearch) | Anime catalog |
| [Shaka Player](https://github.com/shaka-project/shaka-player) | Video playback |
| [JavascriptSubtitlesOctopus](https://github.com/libass/JavascriptSubtitlesOctopus) | ASS subtitle rendering |
| [Material Symbols](https://github.com/google/material-design-icons) | Interface icons |
| [Electron](https://github.com/electron/electron) / [Chromium](https://www.chromium.org/) | Server-side browser for sign-in |
| [MyAnimeList](https://myanimelist.net/) / [Shikimori](https://shikimori.rip/) | Anime info and lists |

License notices for bundled assets live in `licenses/` and `public/libass/`. Electron and Chromium notices ship with the runtime installed in Docker.

## License

[MIT](LICENSE). Bundled third-party assets keep their own licenses — see `licenses/` and `public/libass/`.

[Licenses and corresponding sources](docs/LICENSING.md).
