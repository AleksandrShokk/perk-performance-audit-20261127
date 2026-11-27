import { isAxiosError } from 'axios'

export function downloadFile(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Keep HTTP status/step-up details when a file request returns JSON instead of a file. */
export async function downloadResponse(request: Promise<Blob>): Promise<Blob> {
  try {
    return await request
  } catch (error) {
    if (
      isAxiosError(error) &&
      error.response?.data instanceof Blob &&
      error.response.data.size <= 65536
    ) {
      const blob = error.response.data
      if (
        String(error.response.headers['content-type'] ?? blob.type).includes(
          'json'
        )
      ) {
        try {
          error.response.data = JSON.parse(await blob.text())
        } catch {
          /* Fall back to the HTTP status message. */
        }
      }
    }
    throw error
  }
}
