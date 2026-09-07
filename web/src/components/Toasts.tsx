import { useEffect } from 'react'
import { useStore } from '../store'
import type { ToastItem } from '../store'

function Toast({ toast }: { toast: ToastItem }) {
  const dismiss = useStore((s) => s.dismissToast)
  useEffect(() => {
    const t = setTimeout(() => dismiss(toast.id), 12000)
    return () => clearTimeout(t)
  }, [toast.id, dismiss])
  return (
    <div className={`toast ${toast.level}`} onClick={() => dismiss(toast.id)}>
      <div className="toast-title">{toast.title}</div>
      {toast.message}
    </div>
  )
}

export default function Toasts() {
  const toasts = useStore((s) => s.toasts)
  return (
    <div className="toast-wrap">
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} />
      ))}
    </div>
  )
}
