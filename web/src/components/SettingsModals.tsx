// Settings modals: AI model / general / Feishu — backed by GET/PUT /api/settings.
import { useEffect, useState, ReactNode } from 'react'
import { api } from '../api/client'
import { useStore } from '../store'
import type { SettingsPayload } from '../api/types'

export default function SettingsModals() {
  const modal = useStore((s) => s.modal)
  const openModal = useStore((s) => s.openModal)
  const validationBody = useStore((s) => s.validationBody)
  const [settings, setSettings] = useState<SettingsPayload | null>(null)

  useEffect(() => {
    if (modal && modal !== 'validation' && !settings) {
      api.get('/api/settings').then((r) => {
        if (r.ok) setSettings(r.settings as SettingsPayload)
      })
    }
  }, [modal, settings])

  function close() {
    openModal(null)
    setSettings(null)
  }

  if (!modal) return null

  if (modal === 'validation' && validationBody) {
    return (
      <div className="modal-overlay" onClick={close}>
        <div className="modal" style={{ width: 'min(760px, 94vw)' }} onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">
            {validationBody.title}
            <button onClick={close}>关闭</button>
          </div>
          <div className="modal-body">
            <div style={{ whiteSpace: 'pre-wrap', marginBottom: 10 }}>{validationBody.summary}</div>
            <pre style={{ background: 'var(--bg)', padding: 10, borderRadius: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {validationBody.body}
            </pre>
          </div>
          <div className="modal-footer">
            <button
              className="primary"
              onClick={() => {
                navigator.clipboard.writeText(validationBody.body)
                useStore.getState().pushToast({ level: 'success', title: '已复制', message: '' })
              }}
            >
              复制调试信息
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (!settings) {
    return (
      <div className="modal-overlay" onClick={close}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">加载设置中…</div>
        </div>
      </div>
    )
  }

  if (modal === 'ai') return <AiModelModal settings={settings} onClose={close} />
  if (modal === 'general') return <GeneralModal settings={settings} onClose={close} />
  if (modal === 'feishu') return <FeishuModal settings={settings} onClose={close} />
  return null
}

async function saveSettings(settings: SettingsPayload): Promise<string | null> {
  const r = await api.put('/api/settings', settings)
  return r.ok ? null : (r.error ?? '保存失败')
}

function AiModelModal({ settings, onClose }: { settings: SettingsPayload; onClose: () => void }) {
  const provider = settings.provider as Record<string, unknown>
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(String(provider.base_url ?? ''))
  const [model, setModel] = useState(String(provider.model ?? ''))
  const [thinking, setThinking] = useState(Boolean(provider.thinking))
  const [effort, setEffort] = useState(String(provider.reasoning_effort ?? 'high'))
  const [error, setError] = useState('')

  async function save() {
    if (apiKey.trim()) provider.api_key = apiKey.trim()
    provider.base_url = baseUrl.trim()
    provider.model = model.trim()
    provider.thinking = thinking
    provider.reasoning_effort = effort
    const err = await saveSettings(settings)
    if (err) setError(err)
    else onClose()
  }

  return (
    <Modal title="AI 模型设置" onClose={onClose} onSave={save} error={error}>
      <div className="form-row">
        <label>API Key</label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={
            provider.api_key_configured
              ? `已配置（${String(provider.api_key_masked ?? '••••')}），留空保持不变`
              : '请输入 API Key'
          }
        />
      </div>
      <div className="form-row">
        <label>Base URL</label>
        <input type="text" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
      </div>
      <div className="form-hint">OpenAI 兼容接口地址，如 https://api.deepseek.com</div>
      <div className="form-row">
        <label>模型</label>
        <input type="text" value={model} onChange={(e) => setModel(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Thinking（深度思考）</label>
        <input type="checkbox" checked={thinking} onChange={(e) => setThinking(e.target.checked)} />
      </div>
      <div className="form-row">
        <label>Reasoning Effort</label>
        <select value={effort} onChange={(e) => setEffort(e.target.value)}>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="max">max</option>
        </select>
      </div>
    </Modal>
  )
}

function GeneralModal({ settings, onClose }: { settings: SettingsPayload; onClose: () => void }) {
  const general = settings.general as Record<string, unknown>
  const [state, setState] = useState({
    analysis_bar_count: Number(general.analysis_bar_count ?? 100),
    incremental_max_new_bars: Number(general.incremental_max_new_bars ?? 10),
    decision_stance: String(general.decision_stance ?? 'balanced'),
    enable_next_bar_prediction: Boolean(general.enable_next_bar_prediction),
    auto_resume_chart_after_analysis: Boolean(general.auto_resume_chart_after_analysis),
    cancel_keep_analysis_on_retry: Boolean(general.cancel_keep_analysis_on_retry),
    alert_on_order_opportunity: Boolean(general.alert_on_order_opportunity),
    decision_confidence_threshold: Number(general.decision_confidence_threshold ?? 40),
    structure_flip_cooldown_bars: Number(general.structure_flip_cooldown_bars ?? 3),
    refresh_interval_ms: Number(general.refresh_interval_ms ?? 1000),
    kline_adjust: String(general.kline_adjust ?? 'qfq'),
  })
  const [error, setError] = useState('')

  function set<K extends keyof typeof state>(key: K, value: (typeof state)[K]) {
    setState((s) => ({ ...s, [key]: value }))
  }

  async function save() {
    Object.assign(general, state)
    const err = await saveSettings(settings)
    if (err) setError(err)
    else onClose()
  }

  return (
    <Modal title="其他通用设置" onClose={onClose} onSave={save} error={error}>
      <div className="form-row">
        <label>分析K线数量</label>
        <input
          type="number"
          value={state.analysis_bar_count}
          onChange={(e) => set('analysis_bar_count', Number(e.target.value))}
        />
      </div>
      <div className="form-row">
        <label>增量分析最大新增K线</label>
        <input
          type="number"
          value={state.incremental_max_new_bars}
          onChange={(e) => set('incremental_max_new_bars', Number(e.target.value))}
        />
      </div>
      <div className="form-row">
        <label>决策倾向</label>
        <select value={state.decision_stance} onChange={(e) => set('decision_stance', e.target.value)}>
          <option value="balanced">balanced（均衡）</option>
          <option value="aggressive">aggressive（激进）</option>
          <option value="conservative">conservative（保守）</option>
        </select>
      </div>
      <div className="form-row">
        <label>决策信心阈值（%）</label>
        <input
          type="number"
          value={state.decision_confidence_threshold}
          onChange={(e) => set('decision_confidence_threshold', Number(e.target.value))}
        />
      </div>
      <div className="form-row">
        <label>下一根K线预测</label>
        <input
          type="checkbox"
          checked={state.enable_next_bar_prediction}
          onChange={(e) => set('enable_next_bar_prediction', e.target.checked)}
        />
      </div>
      <div className="form-row">
        <label>分析后恢复图表刷新</label>
        <input
          type="checkbox"
          checked={state.auto_resume_chart_after_analysis}
          onChange={(e) => set('auto_resume_chart_after_analysis', e.target.checked)}
        />
      </div>
      <div className="form-row">
        <label>重试时关闭持续跟踪</label>
        <input
          type="checkbox"
          checked={state.cancel_keep_analysis_on_retry}
          onChange={(e) => set('cancel_keep_analysis_on_retry', e.target.checked)}
        />
      </div>
      <div className="form-row">
        <label>下单机会弹窗提醒</label>
        <input
          type="checkbox"
          checked={state.alert_on_order_opportunity}
          onChange={(e) => set('alert_on_order_opportunity', e.target.checked)}
        />
      </div>
      <div className="form-row">
        <label>结构翻转冷却（K线数）</label>
        <input
          type="number"
          value={state.structure_flip_cooldown_bars}
          onChange={(e) => set('structure_flip_cooldown_bars', Number(e.target.value))}
        />
      </div>
      <div className="form-row">
        <label>刷新间隔（毫秒）</label>
        <input
          type="number"
          value={state.refresh_interval_ms}
          onChange={(e) => set('refresh_interval_ms', Number(e.target.value))}
        />
      </div>
      <div className="form-row">
        <label>K线复权</label>
        <select value={state.kline_adjust} onChange={(e) => set('kline_adjust', e.target.value)}>
          <option value="qfq">前复权</option>
          <option value="hfq">后复权</option>
          <option value="none">不复权</option>
        </select>
      </div>
    </Modal>
  )
}

function FeishuModal({ settings, onClose }: { settings: SettingsPayload; onClose: () => void }) {
  const feishu = settings.feishu as Record<string, unknown>
  const [webhookUrl, setWebhookUrl] = useState(String(feishu.webhook_url ?? ''))
  const [secret, setSecret] = useState(String(feishu.secret ?? ''))
  const [enabled, setEnabled] = useState(Boolean(feishu.enabled ?? true))
  const [notifyOnOrderOnly, setNotifyOnOrderOnly] = useState(Boolean(feishu.notify_on_order_only ?? true))
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const [testing, setTesting] = useState(false)

  async function save() {
    feishu.webhook_url = webhookUrl.trim()
    if (secret.trim()) feishu.secret = secret.trim()
    feishu.enabled = enabled
    feishu.notify_on_order_only = notifyOnOrderOnly
    const err = await saveSettings(settings)
    if (err) setError(err)
    else onClose()
  }

  async function test() {
    setTesting(true)
    setMsg('')
    const r = await api.post('/api/settings/feishu/test', { webhook_url: webhookUrl, secret })
    setTesting(false)
    if (r.ok) setMsg(r.message ?? '发送成功')
    else setError(r.error ?? '发送失败')
  }

  return (
    <Modal title="飞书发送通知设置" onClose={onClose} onSave={save} error={error} info={msg}>
      <div className="form-row">
        <label>启用飞书通知</label>
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
      </div>
      <div className="form-row">
        <label>Webhook URL</label>
        <input type="text" value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} />
      </div>
      <div className="form-row">
        <label>签名 Secret</label>
        <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="留空表示未启用签名" />
      </div>
      <div className="form-row">
        <label>仅下单信号时通知</label>
        <input
          type="checkbox"
          checked={notifyOnOrderOnly}
          onChange={(e) => setNotifyOnOrderOnly(e.target.checked)}
        />
      </div>
      <div className="form-row">
        <label />
        <button onClick={test} disabled={testing || !webhookUrl.trim()}>
          {testing ? '发送中…' : '发送测试消息'}
        </button>
      </div>
    </Modal>
  )
}

function Modal({
  title,
  onClose,
  onSave,
  children,
  error,
  info,
}: {
  title: string
  onClose: () => void
  onSave: () => void
  children: ReactNode
  error?: string
  info?: string
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          {title}
          <button onClick={onClose}>×</button>
        </div>
        <div className="modal-body">{children}</div>
        {(error || info) && (
          <div className="modal-body" style={{ paddingTop: 0 }}>
            {error && <div style={{ color: 'var(--danger)', whiteSpace: 'pre-wrap' }}>{error}</div>}
            {info && <div style={{ color: 'var(--success)', whiteSpace: 'pre-wrap' }}>{info}</div>}
          </div>
        )}
        <div className="modal-footer">
          <button onClick={onClose}>取消</button>
          <button className="primary" onClick={onSave}>
            保存
          </button>
        </div>
      </div>
    </div>
  )
}
