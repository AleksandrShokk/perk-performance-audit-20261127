'use client'

import { Package } from 'lucide-react'
import Image from 'next/image'
import { useState } from 'react'

export function ProductLabel({
  title,
  article,
  photo
}: {
  title: string
  article?: string
  photo?: string | null
}) {
  const [failed, setFailed] = useState<string | null>(null)
  return (
    <div className='product-label'>
      {photo && failed !== photo ? (
        <Image
          src={photo}
          onError={() => setFailed(photo)}
          alt=''
          width={38}
          height={48}
          unoptimized
          className='product-photo'
        />
      ) : (
        <span className='product-photo placeholder'>
          <Package size={18} />
        </span>
      )}
      <span>
        <strong>{title}</strong>
        <small>{article || '—'}</small>
      </span>
    </div>
  )
}
