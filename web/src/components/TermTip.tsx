// 术语提示：桌面 hover / 触屏点按 双态气泡，替换原生 title。
import { useEffect, useRef, useState } from 'react'

/** 包裹一段术语文本：悬停或点按弹出含义解释。 */
export default function TermTip({ text, hint, className }: { text: string; hint?: string; className?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: TouchEvent | MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    // 触屏场景：点其他区域关闭（桌面 hover 离开自然关闭）
    document.addEventListener('touchstart', onDoc, { passive: true })
    document.addEventListener('click', onDoc)
    return () => {
      document.removeEventListener('touchstart', onDoc)
      document.removeEventListener('click', onDoc)
    }
  }, [open])

  if (!hint) return <span className={className}>{text}</span>
  return (
    <span
      ref={ref}
      className={`term${open ? ' open' : ''}${className ? ' ' + className : ''}`}
      onClick={(e) => {
        e.stopPropagation()
        setOpen((v) => !v)
      }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {text}
      {open && (
        <span className="term-pop" role="tooltip">
          {hint}
        </span>
      )}
    </span>
  )
}
