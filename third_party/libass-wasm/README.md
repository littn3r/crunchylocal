# Corresponding sources for the subtitle renderer

The distributed worker JS and WASM are the unmodified `libass-wasm@4.1.0` npm release. The JavaScript wrapper has the local change in `clear-subtitles.patch` (13 October 2026). `manifest.json` records their SHA-256 hashes, upstream commit and exact dependency commits, including FreeType's nested dlg dependency.

The **complete source bundle** is included in this project at [public/source/libass-wasm-4.1.0-source.tar.gz](../../public/source/libass-wasm-4.1.0-source.tar.gz). It is also served by the player at `/source/libass-wasm-4.1.0-source.tar.gz`; `/source/manifest.json`, `/source/clear-subtitles.patch` and `/source/COPYRIGHT` are available alongside it. No account is required to download these materials.

The archive includes upstream source, build recipes, interface definitions, patches, all library submodule sources and Liberation Sans font licensing. You do not need to fetch Git submodules. Library copyright and licenses are preserved. FriBidi is LGPL-2.1-or-later; other components retain their original licenses. The project's MIT license does not replace these licenses.

## Build or replace the library

From the project directory, with Docker running:

```sh
docker build --platform linux/amd64 -t crunchy-subtitles-build:4.1.0 -f third_party/libass-wasm/Dockerfile .
docker run --rm --platform linux/amd64 --cpus=2 --memory=3g --network=none -e EMCC_CORES=2 --mount "type=bind,source=$PWD,target=/project" --mount type=volume,source=crunchy-subtitles-cache,target=/emsdk/upstream/emscripten/cache crunchy-subtitles-build:4.1.0 python3 /project/third_party/libass-wasm/rebuild.py
```

The build image pins Emscripten 3.1.15 by digest, matching the upstream release toolchain. The image build needs internet access for standard build tools; compilation uses the supplied sources with networking disabled. On ARM computers this uses x86 emulation and can take considerably longer. The first compilation also prepares Emscripten's system libraries. The cache volume speeds up subsequent builds.

Output is in `.build/subtitles/libass-wasm-4.1.0/dist/js/`. To use a modified FriBidi, edit `.build/subtitles/libass-wasm-4.1.0/lib/fribidi`, then remove `.build/subtitles/libass-wasm-4.1.0/build/lib/fribidi` and `.build/subtitles/libass-wasm-4.1.0/dist/libraries/lib/libfribidi.a` before running the build again. There is no signature check preventing use of a replacement worker.

Add `--install` to the Python invocation to copy the successful build into `public/libass/`. Rebuild the application image using your usual Compose command. If distributing your changed binary, update its manifest hashes, describe your changes and provide its corresponding changed sources, patch and build instructions alongside it. Keep the LGPL license and notices. The original archive checksum protects the bundled starting sources; it does not prohibit modifying the extracted sources.

Byte-for-byte reproduction is not promised: build paths, tool versions and generated metadata may change the bytes. The bundle identifies the sources used by upstream.

## Download-only use

If you obtained only the files served by the player, download the source archive and the adjacent `clear-subtitles.patch`, `COPYRIGHT`, `manifest.json`, `Dockerfile` and `rebuild.py`. The archive itself contains a complete upstream tree and all library sources. Extract it and build its worker with its included Dockerfile:

```sh
tar -xzf libass-wasm-4.1.0-source.tar.gz
cd libass-wasm-4.1.0
docker build --platform linux/amd64 -t crunchy-subtitles-source:4.1.0 .
docker run --rm --platform linux/amd64 --cpus=2 --memory=3g --network=none -e EMCC_CORES=2 --mount "type=bind,source=$PWD,target=/code" crunchy-subtitles-source:4.1.0 make 'JSO_MAKE=emmake make -j 2' dist/js/subtitles-octopus-worker.js
```

To apply the local wrapper change, run `patch -p1 -i ../clear-subtitles.patch` from the extracted directory. The upstream `all` target expects Git metadata for notice generation and builds an unused asm.js worker; use the worker target above. Retain the supplied `COPYRIGHT`, `assets/OFL.txt` and Emscripten/system notices when redistributing the rebuilt worker. The wrapper's preferred source is `src/subtitles-octopus.js`; prepend the comment-form copyright notices when generating the distributed wrapper, as done by the project's `rebuild.py`.
