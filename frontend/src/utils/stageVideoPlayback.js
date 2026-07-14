/**
 * Stage video is ambient playback: it may run only while the hero itself is
 * the foreground surface. Keep this policy independent from the DOM player so
 * every asynchronous playback path can apply the same decision.
 */
export function shouldPlayStageVideo({
  viewActive,
  layoutMode,
  slideshowActive,
  compareActive,
  documentVisible,
  windowFocused,
}) {
  return viewActive
    && layoutMode === 'stage'
    && !slideshowActive
    && !compareActive
    && documentVisible
    && windowFocused
}
