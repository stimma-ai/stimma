<template>
  <!--
    The one tile signal. Black glass, one height, one radius, mono facts, white
    glyphs in both themes. Tiles place chips at a 6px inset in the corners;
    nothing on a tile carries its own color except an active favorite heart.
  -->
  <span
    class="inline-flex h-5 max-w-full shrink-0 items-center gap-1 whitespace-nowrap rounded-md bg-black/55 px-1.5 font-mono text-[11px] font-medium leading-none tabular-nums text-white/90 backdrop-blur-md [&>svg]:h-3 [&>svg]:w-3 [&>svg]:shrink-0"
  >
    <slot />
  </span>
</template>
