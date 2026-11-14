import { useEffect, useEffectEvent, type RefObject } from 'react'

/** Keyboard behavior for the app's custom modal popovers. Native dialogs use showModal(). */
export function useDialogFocus(
  open: boolean,
  dialog: RefObject<HTMLElement | null>,
  trigger: RefObject<HTMLElement | null>,
  onClose: () => void,
) {
  const close = useEffectEvent(onClose)
  useEffect(() => {
    const element = dialog.current
    if (!open || !element) return
    const panel: HTMLElement = element
    const previous = trigger.current ?? document.activeElement
    const controls = () => [...panel.querySelectorAll<HTMLElement>(
      'button:not(:disabled), summary, a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
    )].filter((node) => {
      if (node.closest('[hidden], [inert]')) return false
      for (let ancestor: HTMLElement | null = node; ancestor; ancestor = ancestor.parentElement) {
        const style = getComputedStyle(ancestor)
        if (style.display === 'none' || style.visibility === 'hidden') return false
        if (ancestor instanceof HTMLDetailsElement && !ancestor.open && !ancestor.querySelector('summary')?.contains(node)) return false
        if (ancestor === panel) break
      }
      return true
    })

    // Keep the rest of the workspace outside this modal's tab and accessibility trees.
    const siblings: Element[] = []
    let branch: Element = panel
    while (branch.parentElement) {
      for (const sibling of branch.parentElement.children) {
        if (sibling !== branch && !sibling.hasAttribute('inert')) {
          sibling.setAttribute('inert', '')
          siblings.push(sibling)
        }
      }
      branch = branch.parentElement
      if (branch === document.body) break
    }
    ;(controls()[0] ?? panel).focus()

    function keyboard(event: KeyboardEvent) {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault()
        close()
      } else if (event.key === 'Tab') {
        const items = controls()
        const first = items[0] ?? panel
        const last = items.at(-1) ?? panel
        if (!panel.contains(document.activeElement) || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
          event.preventDefault()
          ;(event.shiftKey ? last : first).focus()
        }
      }
    }
    document.addEventListener('keydown', keyboard)
    return () => {
      document.removeEventListener('keydown', keyboard)
      siblings.forEach((node) => node.removeAttribute('inert'))
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [open, dialog, trigger])
}
