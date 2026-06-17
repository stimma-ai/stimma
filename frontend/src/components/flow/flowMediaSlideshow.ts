import type { InjectionKey } from 'vue'

export interface FlowMediaSlideshowApi {
  open: (mediaId: number, options?: { mediaIds?: number[]; startIndex?: number }) => void
}

export const flowMediaSlideshowKey: InjectionKey<FlowMediaSlideshowApi> = Symbol('flow-media-slideshow')
