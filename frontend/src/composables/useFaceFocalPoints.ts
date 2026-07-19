import { reactive } from 'vue'
import { useMediaApi } from './useMediaApi'

/**
 * Shared, cached lookup of face-aware focal points for static images.
 *
 * The backend bakes a square face-centered crop into `mode=crop` thumbnails,
 * which frames faces perfectly in square tiles. In a non-square container
 * (e.g. the wide, short "Jump back in" cards) object-cover re-crops that square
 * from dead center and can push faces out of frame. The fix is to serve the
 * thumbnail in `fit` mode and set `object-position` to the face centroid, so
 * object-cover keeps the face framed at any container aspect.
 *
 * This composable batch-fetches those centroids (`/media/face-positions`) and
 * caches them process-wide so repeated renders and multiple views share one
 * request per media id.
 */

// media_id -> CSS object-position string ("x% y%"), or null when the media has
// no detected faces. Absent key = not yet fetched.
const cache = reactive<Record<number, string | null>>({})
const inflight = new Set<number>()

const { getFaceObjectPositions } = useMediaApi()

function toId(value: unknown): number | null {
  const id = typeof value === 'number' ? value : parseInt(String(value), 10)
  return Number.isFinite(id) ? id : null
}

export function useFaceFocalPoints() {
  /** Ensure focal points for these media ids are fetched (idempotent). */
  async function request(ids: Array<number | null | undefined>): Promise<void> {
    const need = [...new Set(
      ids.map(toId).filter((id): id is number => id != null && !(id in cache) && !inflight.has(id))
    )]
    if (!need.length) return
    need.forEach(id => inflight.add(id))
    try {
      const positions = await getFaceObjectPositions(need)
      for (const id of need) {
        const pos = positions?.[id] ?? positions?.[String(id)]
        cache[id] = pos ? `${pos.x}% ${pos.y}%` : null
      }
    } catch {
      // Leave uncached so a later render can retry; default centering applies
      // in the meantime.
    } finally {
      need.forEach(id => inflight.delete(id))
    }
  }

  /**
   * CSS object-position for the media's face centroid, or undefined when
   * unknown or the media has no faces (caller falls back to default centering).
   */
  function positionOf(id: number | null | undefined): string | undefined {
    const key = toId(id)
    if (key == null) return undefined
    return cache[key] || undefined
  }

  return { request, positionOf }
}
