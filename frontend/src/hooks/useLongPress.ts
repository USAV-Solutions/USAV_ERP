import { useCallback, useMemo, useRef, type MouseEvent, type PointerEvent } from 'react'

interface UseLongPressOptions {
  delayMs?: number
  shouldStart?: (target: EventTarget | null) => boolean
}

const defaultShouldStart = (target: EventTarget | null): boolean => {
  if (!(target instanceof Element)) {
    return true
  }

  // Avoid hijacking normal interactions inside action controls.
  if (target.closest('button, a, input, textarea, select, [role="button"]')) {
    return false
  }

  return true
}

export function useLongPress<T>(
  onLongPress: (payload: T) => void,
  payload: T,
  options: UseLongPressOptions = {},
) {
  const timerRef = useRef<number | null>(null)
  const didLongPressRef = useRef(false)

  const delayMs = options.delayMs ?? 450
  const shouldStart = options.shouldStart ?? defaultShouldStart

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const start = useCallback(
    (target: EventTarget | null, button?: number) => {
      // Only primary mouse button should trigger long-press.
      if (button !== undefined && button !== 0) {
        return
      }

      if (!shouldStart(target)) {
        return
      }

      didLongPressRef.current = false
      clearTimer()
      timerRef.current = window.setTimeout(() => {
        didLongPressRef.current = true
        onLongPress(payload)
      }, delayMs)
    },
    [clearTimer, delayMs, onLongPress, payload, shouldStart],
  )

  const end = useCallback(() => {
    clearTimer()
  }, [clearTimer])

  return useMemo(
    () => ({
      onPointerDown: (event: PointerEvent) => start(event.target, event.button),
      onPointerUp: end,
      onPointerLeave: end,
      onPointerCancel: end,
      onContextMenu: (event: MouseEvent) => {
        if (didLongPressRef.current) {
          event.preventDefault()
        }
      },
      onClickCapture: (event: MouseEvent) => {
        if (didLongPressRef.current) {
          event.preventDefault()
          event.stopPropagation()
          didLongPressRef.current = false
        }
      },
    }),
    [end, start],
  )
}
