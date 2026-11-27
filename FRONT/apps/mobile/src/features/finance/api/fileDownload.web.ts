export async function saveTemplate(bytes: ArrayBuffer, mimeType: string) {
  const url = URL.createObjectURL(new Blob([bytes], { type: mimeType }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'perk-cost-template.xlsx'
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
