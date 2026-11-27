import { palette, radius, spacing, typography } from '@app/tokens'

function variables(scheme: keyof typeof palette) {
  const p = palette[scheme]
  return {
    '--background': p.background.screen,
    '--foreground': p.text.primary,
    '--card': p.background.card,
    '--card-foreground': p.text.primary,
    '--popover': p.background.card,
    '--popover-foreground': p.text.primary,
    '--primary': p.accent,
    '--primary-foreground': scheme === 'dark' ? p.background.screen : '#FFFFFF',
    '--secondary': `color-mix(in srgb, ${p.accent} 9%, ${p.background.card})`,
    '--secondary-foreground': p.text.primary,
    '--muted': `color-mix(in srgb, ${p.text.secondary} 7%, ${p.background.card})`,
    '--muted-foreground': p.text.secondary,
    '--accent': `color-mix(in srgb, ${p.accent} 12%, ${p.background.card})`,
    '--accent-foreground': p.accent,
    '--destructive': p.error,
    '--border': p.border,
    '--input': p.border,
    '--ring': p.accent,
    '--success': p.success,
    '--radius': `${radius.control}px`,
    '--radius-card': `${radius.card}px`,
    '--font-body-size': `${typography.label.fontSize}px`,
    '--content-gap': `${spacing.xl}px`,
    '--sidebar': p.background.screen,
    '--sidebar-foreground': p.text.secondary,
    '--sidebar-primary': p.accent,
    '--sidebar-accent': `color-mix(in srgb, ${p.accent} 12%, transparent)`,
    '--sidebar-accent-foreground': p.accent,
    '--sidebar-border': p.border,
    '--sidebar-ring': p.accent
  }
}
export function ThemeTokens() {
  const css = Object.entries(palette)
    .map(
      ([name]) =>
        `${name === 'light' ? ':root' : '.dark'}{${Object.entries(
          variables(name as keyof typeof palette)
        )
          .map(([key, value]) => `${key}:${value}`)
          .join(';')}}`
    )
    .join('')
  return <style>{css}</style>
}
