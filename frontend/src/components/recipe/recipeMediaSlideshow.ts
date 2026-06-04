import type { InjectionKey } from 'vue'

export interface RecipeMediaSlideshowApi {
  open: (mediaId: number, options?: { mediaIds?: number[]; startIndex?: number }) => void
}

export const recipeMediaSlideshowKey: InjectionKey<RecipeMediaSlideshowApi> = Symbol('recipe-media-slideshow')
