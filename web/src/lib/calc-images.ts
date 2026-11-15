/** One decoded source page per open calculation, shared by every evidence crop. */
export function calculationImages(load: (docId: string, page: number, signal: AbortSignal) => Promise<Blob>) {
  const pages = new Map<string, Promise<HTMLImageElement>>()
  const releases = new Set<() => void>()
  return {
    get(docId: string, page: number) {
      const key = JSON.stringify([docId, page])
      let pending = pages.get(key)
      if (!pending) {
        const controller = new AbortController()
        let image: HTMLImageElement | undefined
        let url = ''
        const release = () => {
          controller.abort()
          if (image) image.src = ''
          if (url) URL.revokeObjectURL(url)
        }
        releases.add(release)
        pending = load(docId, page, controller.signal).then(async (blob) => {
          controller.signal.throwIfAborted()
          image = new Image()
          url = URL.createObjectURL(blob)
          image.src = url
          await image.decode()
          controller.signal.throwIfAborted()
          return image
        }).catch((error: unknown) => {
          if (pages.get(key) === pending) pages.delete(key)
          releases.delete(release)
          release()
          throw error
        })
        pages.set(key, pending)
      }
      return pending
    },
    clear() {
      pages.clear()
      for (const release of releases) release()
      releases.clear()
    },
  }
}
