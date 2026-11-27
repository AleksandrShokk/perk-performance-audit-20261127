'use client'

import { ChevronLeft, ChevronRight, Package } from 'lucide-react'
import Image from 'next/image'
import { useRef, useState } from 'react'

import { Button } from '@/components/ui/button'

export function ProductGallery({
  photos,
  title
}: {
  photos: string[]
  title: string
}) {
  const track = useRef<HTMLDivElement>(null)
  const [index, setIndex] = useState(0)
  const [failed, setFailed] = useState(new Set<number>())
  const select = (next: number) => {
    if (track.current)
      track.current.scrollTo({ left: next * track.current.clientWidth })
  }
  if (!photos.length)
    return (
      <div className='product-gallery-empty'>
        <Package
          size={64}
          strokeWidth={1}
        />
      </div>
    )
  return (
    <div className='product-gallery'>
      <div className='product-gallery-main'>
        <div
          className='product-gallery-track'
          ref={track}
          aria-label='Фотографии товара'
          onScroll={event =>
            setIndex(
              Math.round(
                event.currentTarget.scrollLeft /
                  Math.max(1, event.currentTarget.clientWidth)
              )
            )
          }
        >
          {photos.map((photo, i) => (
            <div
              className='product-gallery-slide'
              key={`${photo}:${i}`}
            >
              {failed.has(i) ? (
                <Package
                  size={64}
                  strokeWidth={1}
                />
              ) : (
                <Image
                  src={photo}
                  alt={`${title} · фото ${i + 1}`}
                  width={520}
                  height={620}
                  unoptimized
                  loading={i === 0 ? 'eager' : 'lazy'}
                  draggable={false}
                  onError={() => setFailed(current => new Set(current).add(i))}
                />
              )}
            </div>
          ))}
        </div>
        {photos.length > 1 && (
          <>
            <Button
              className='gallery-arrow previous'
              variant='secondary'
              size='icon'
              aria-label='Предыдущее фото'
              disabled={index === 0}
              onClick={() => select(index - 1)}
            >
              <ChevronLeft size={18} />
            </Button>
            <Button
              className='gallery-arrow next'
              variant='secondary'
              size='icon'
              aria-label='Следующее фото'
              disabled={index >= photos.length - 1}
              onClick={() => select(index + 1)}
            >
              <ChevronRight size={18} />
            </Button>
            <span
              className='gallery-position'
              aria-live='polite'
            >
              {index + 1} / {photos.length}
            </span>
          </>
        )}
      </div>
      {photos.length > 1 && (
        <div
          className='gallery-thumbnails'
          role='group'
          aria-label='Выбрать фотографию'
        >
          {photos.map((photo, i) => (
            <button
              key={`${photo}:${i}`}
              aria-label={`Фото ${i + 1}`}
              aria-pressed={index === i}
              onClick={() => select(i)}
            >
              {failed.has(i) ? (
                <Package size={18} />
              ) : (
                <Image
                  src={photo}
                  alt=''
                  width={54}
                  height={64}
                  unoptimized
                  draggable={false}
                />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
