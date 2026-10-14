// Build against a local ZenKit checkout instead of npm: `ZENKIT_DEV=../ZenKit pnpm install`
// (build ZenKit first). The deps are rewritten to link: and the lockfile is left alone, so it
// keeps describing the npm versions; a plain `pnpm install --frozen-lockfile
// --config.optimistic-repeat-install=false` goes back to them.
const dir = process.env.ZENKIT_DEV;
const local = dir && {
  "@nynxz/zenkit-ui": `link:${dir}/packages/ui`,
  "@nynxz/zenkit-nodekit": `link:${dir}/packages/nodekit`,
};

function readPackage(pkg) {
  if (!local) return pkg;
  for (const field of ["dependencies", "devDependencies"])
    for (const name of Object.keys(pkg[field] ?? {}))
      if (local[name]) pkg[field][name] = local[name];
  return pkg;
}

module.exports = {
  hooks: {
    readPackage,
    updateConfig: (config) =>
      local ? { ...config, useLockfile: false, optimisticRepeatInstall: false } : config,
  },
};
