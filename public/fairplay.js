/* Crunchyroll FairPlay uses the legacy Apple CDM and the complete SKD query. */
(() => {
  let installed = false;
  function qualities(manifest) {
    return [...new Set([...manifest.matchAll(/^#EXT-X-STREAM-INF:.*?RESOLUTION=\d+x(\d+)(?:,|$)/gm)]
      .map(match => Number(match[1])).filter(height => height > 0 && height <= 4320))].sort((a, b) => b - a);
  }
  function qualityUrl(url, height) {
    const result = new URL(url);
    if (height === 'auto') result.searchParams.delete('quality');
    else result.searchParams.set('quality', String(height));
    return result.href;
  }
  function contentId(uri) {
    const start = uri.indexOf('?');
    if (!uri.startsWith('skd://') || start < 0) throw new Error('Invalid FairPlay content identifier.');
    return uri.slice(start);
  }
  function install(environment, shaka) {
    if (installed) return;
    shaka.polyfill.PatchedMediaKeysApple.install();
    const capabilities = environment.navigator.mediaCapabilities;
    if (capabilities?.decodingInfo) {
      const nativeDecode = capabilities.decodingInfo.bind(capabilities);
      capabilities.decodingInfo = async configuration => {
        const drm = configuration.keySystemConfiguration;
        if (drm?.keySystem !== 'com.apple.fps.1_0') return nativeDecode(configuration);
        // Native MediaCapabilities does not consult the legacy EME polyfill.
        const result = {configuration, supported: false, smooth: true, powerEfficient: true, keySystemAccess: null};
        try {
          result.keySystemAccess = await environment.navigator.requestMediaKeySystemAccess(drm.keySystem, [{
            initDataTypes: ['skd'],
            ...(configuration.audio ? {audioCapabilities: [{contentType: 'audio/mp4'}]} : {}),
            ...(configuration.video ? {videoCapabilities: [{contentType: 'video/mp4'}]} : {})
          }]);
          result.supported = true;
        } catch { /* Leave unsupported legacy configurations unavailable. */ }
        return result;
      };
    }
    installed = true;
  }
  const api = {contentId, install, qualities, qualityUrl};
  if (typeof window !== 'undefined') window.FairPlaySupport = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
