const { withProjectBuildGradle, withGradleProperties } = require('@expo/config-plugins');

const LINPHONE_REPO = 'https://download.linphone.org/maven_repository';

function addLinphoneMaven(buildGradle) {
  if (buildGradle.includes(LINPHONE_REPO)) return buildGradle;
  // Inject into allprojects.repositories
  const marker = 'allprojects {';
  const idx = buildGradle.indexOf(marker);
  if (idx === -1) return buildGradle;
  const after = buildGradle.indexOf('repositories {', idx);
  if (after === -1) return buildGradle;
  const insertAt = buildGradle.indexOf('{', after) + 1;
  const snippet = `
    maven { url '${LINPHONE_REPO}' }
`;
  return buildGradle.slice(0, insertAt) + snippet + buildGradle.slice(insertAt);
}

const withLinphoneMaven = (config) =>
  withProjectBuildGradle(config, (cfg) => {
    if (cfg.modResults.language === 'groovy') {
      cfg.modResults.contents = addLinphoneMaven(cfg.modResults.contents);
    }
    return cfg;
  });

const withLargeHeap = (config) =>
  withGradleProperties(config, (cfg) => {
    const upsert = (k, v) => {
      const i = cfg.modResults.findIndex((p) => p.type === 'property' && p.key === k);
      if (i >= 0) cfg.modResults[i] = { type: 'property', key: k, value: v };
      else cfg.modResults.push({ type: 'property', key: k, value: v });
    };
    upsert('android.useAndroidX', 'true');
    upsert('android.enableJetifier', 'true');
    return cfg;
  });

module.exports = (config) => withLargeHeap(withLinphoneMaven(config));
module.exports.default = module.exports;
