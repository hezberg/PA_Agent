import { useEffect } from 'react'
import { useStore } from '../store'
import { CloseIcon } from '../icons'
import type { ToastItem } from '../store'

const DURATION_MS: Record<ToastItem['level'], number> = {
  info: 6000,
  success: 5000,
  warning: 12000,
  error: 20000, // 错误停留更久，且始终可手动关闭
}

function Toast({ toast }: { toast: ToastItem }) {
  const dismiss = useStore((s) => s.dismissToast)
  useEffect(() => {
    const t = setTimeout(() => dismiss(toast.id), DURATION_MS[toast.level])
    return () => clearTimeout(t)
  }, [toast.id, dismiss])
  return (
    <div className={`toast ${toast.level}`}>
      <button className="toast-close" aria-label="关闭提示" onClick={() => dismiss(toast.id)}>
        <CloseIcon />
      </button>
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
