/** Keep extensions in sync with UploadService.ALLOWED_EXTENSIONS. */
export const LIBRARY_UPLOAD_EXTENSIONS = [
  '.jpg', '.jpeg', '.png', '.webp', '.gif',
  '.mp4', '.webm', '.mov', '.avi', '.mkv',
  '.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg', '.svg',
] as const

export const LIBRARY_UPLOAD_ACCEPT = LIBRARY_UPLOAD_EXTENSIONS.join(',')

export function isLibraryUpload(file: Pick<File, 'name'>): boolean {
  const dot = file.name.lastIndexOf('.')
  return dot >= 0 && (LIBRARY_UPLOAD_EXTENSIONS as readonly string[]).includes(file.name.slice(dot).toLowerCase())
}
