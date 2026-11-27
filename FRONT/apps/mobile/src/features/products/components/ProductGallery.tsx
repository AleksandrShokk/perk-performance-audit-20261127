import { useRef, useState } from 'react'
import {
  Pressable,
  ScrollView,
  type ScrollViewInstance,
  View
} from 'react-native'

import { ProductPhoto } from './ProductPhoto'
import { createStyles } from '@/theme'

export function ProductGallery({
  photos,
  title
}: {
  photos: string[]
  title: string
}) {
  const styles = useStyles()
  const pager = useRef<ScrollViewInstance>(null)
  const [page, setPage] = useState(0)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const images = photos.length ? photos : [undefined]

  function select(index: number) {
    pager.current?.scrollTo({ x: index * size.width, animated: true })
  }

  return (
    <View style={styles.gallery}>
      <View
        style={styles.viewport}
        onLayout={({ nativeEvent: { layout } }) => {
          if (layout.width === size.width && layout.height === size.height)
            return
          setSize({ width: layout.width, height: layout.height })
          setPage(0)
          pager.current?.scrollTo({ x: 0, animated: false })
        }}
      >
        {size.width > 0 && (
          <ScrollView
            ref={pager}
            style={styles.pager}
            horizontal
            pagingEnabled
            directionalLockEnabled
            showsHorizontalScrollIndicator={false}
            scrollEnabled={photos.length > 1}
            contentInsetAdjustmentBehavior='never'
            scrollEventThrottle={16}
            onScroll={({ nativeEvent: { contentOffset } }) =>
              setPage(
                Math.max(
                  0,
                  Math.min(
                    images.length - 1,
                    Math.round(contentOffset.x / size.width)
                  )
                )
              )
            }
          >
            {images.map((uri, index) => (
              <ProductPhoto
                key={uri ?? 'placeholder'}
                uri={uri}
                label={`${title}, фото ${index + 1}`}
                style={size}
              />
            ))}
          </ScrollView>
        )}
      </View>
      {photos.length > 1 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentInsetAdjustmentBehavior='never'
          contentContainerStyle={styles.previews}
        >
          {photos.map((uri, index) => (
            <Pressable
              key={uri}
              onPress={() => select(index)}
              accessibilityRole='button'
              accessibilityLabel={`Фото ${index + 1}`}
              accessibilityState={{ selected: index === page }}
              style={[styles.preview, index === page && styles.selected]}
            >
              <ProductPhoto
                uri={uri}
                label={title}
                style={styles.thumbnail}
              />
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  )
}

const useStyles = createStyles(({ colors, spacing, radius }) => ({
  gallery: { gap: spacing.xs },
  viewport: {
    width: '100%',
    aspectRatio: 4 / 3,
    maxHeight: spacing.xxl * 10,
    borderRadius: radius.control,
    backgroundColor: colors.background.screen,
    overflow: 'hidden'
  },
  pager: { flex: 1 },
  previews: { gap: spacing.sm },
  thumbnail: { width: '100%', aspectRatio: 1 },
  preview: {
    width: spacing.xxl * 2,
    padding: spacing.xxs,
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: colors.border
  },
  selected: { backgroundColor: colors.accentSoft, borderColor: colors.accent }
}))
