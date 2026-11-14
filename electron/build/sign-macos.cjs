const fs = require('node:fs')
const { performance } = require('node:perf_hooks')

// osx-sign's default discovery includes all binary-looking resources (bytecode,
// fonts, models, etc.). Those belong in the outer app's resource seal, rather
// than receiving thousands of individual timestamped code signatures.
const MACH_O_MAGIC = new Set([
  'feedface', 'cefaedfe', 'feedfacf', 'cffaedfe',
  'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca',
])

function needsCodeSignature(file) {
  if (fs.statSync(file).isDirectory()) return true // nested apps/frameworks
  const fd = fs.openSync(file, 'r')
  try {
    const magic = Buffer.alloc(4)
    return fs.readSync(fd, magic, 0, 4, 0) === 4 && MACH_O_MAGIC.has(magic.toString('hex'))
  } finally {
    fs.closeSync(fd)
  }
}

function createSigningFilter(originalIgnore) {
  const rules = originalIgnore == null ? [] : Array.isArray(originalIgnore) ? originalIgnore : [originalIgnore]
  return (file) => rules.some(rule => typeof rule === 'function' ? rule(file) : file.match(rule)) || !needsCodeSignature(file)
}

module.exports = async function signMacOS(options) {
  const { signAsync } = require('@electron/osx-sign')
  const ignore = createSigningFilter(options.ignore)
  let signed = 0
  let resources = 0
  const started = performance.now()
  console.log('macOS code signing started (native code and bundles only)')
  await signAsync({
    ...options,
    ignore: file => {
      const skipped = ignore(file)
      if (skipped) resources++
      else signed++
      return skipped
    },
  })
  console.log(`macOS code signing completed in ${((performance.now() - started) / 1000).toFixed(1)}s; ${signed} code targets, ${resources} resources skipped`)
  console.log('macOS notarization follows when enabled')
}

module.exports.needsCodeSignature = needsCodeSignature
module.exports.createSigningFilter = createSigningFilter
