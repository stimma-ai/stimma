/** Keep whole test files together while balancing their measured runtimes. */
export function planShards(files, durations, count) {
  if (!Number.isInteger(count) || count < 1 || count > 64) throw new Error('Invalid shard count')
  const cost = file => durations[file] ?? 20 // New tests are included without a timing entry.
  const bins = Array.from({ length: count }, () => ({ files: [], seconds: 0 }))
  for (const file of [...files].sort((a, b) => cost(b) - cost(a) || a.localeCompare(b))) {
    const bin = bins.reduce((best, candidate) => candidate.seconds < best.seconds ? candidate : best)
    bin.files.push(file)
    bin.seconds += cost(file)
  }
  return bins.map(bin => bin.files.sort())
}

export function selectShard(files, durations, shard) {
  const match = /^([1-9]\d*)\/([1-9]\d*)$/.exec(shard)
  if (!match) throw new Error('Shard must be INDEX/COUNT, starting at 1')
  const index = Number(match[1])
  const count = Number(match[2])
  if (index > count) throw new Error('Shard index exceeds count')
  const selected = planShards(files, durations, count)[index - 1]
  if (!selected.length) throw new Error('Shard has no test files')
  return selected
}
