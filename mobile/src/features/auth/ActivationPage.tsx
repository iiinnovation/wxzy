import { BookOpen, KeyRound, LoaderCircle, ShieldCheck } from 'lucide-react'
import { type FormEvent, useState } from 'react'

interface ActivationPageProps {
  onActivate: (activationCode: string, deviceLabel: string | null) => Promise<void>
}

export function ActivationPage({ onActivate }: ActivationPageProps) {
  const [activationCode, setActivationCode] = useState('')
  const [deviceLabel, setDeviceLabel] = useState('OPPO Find X7 Pro')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting || !activationCode.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await onActivate(activationCode.trim(), deviceLabel.trim() || null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '设备激活失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="page activation-page">
      <header className="activation-page__header">
        <div className="brand-mark" aria-hidden="true">
          <BookOpen size={29} strokeWidth={1.7} />
        </div>
        <div>
          <p className="eyebrow">个人学习工具</p>
          <h1>温习</h1>
        </div>
      </header>

      <section className="activation-panel" aria-labelledby="activation-title">
        <div className="section-heading">
          <KeyRound aria-hidden="true" size={20} />
          <h2 id="activation-title">激活这台设备</h2>
        </div>
        <form onSubmit={onSubmit}>
          <label htmlFor="activation-code">一次性激活码</label>
          <input
            id="activation-code"
            name="activation-code"
            autoCapitalize="none"
            autoComplete="one-time-code"
            spellCheck={false}
            value={activationCode}
            maxLength={256}
            disabled={submitting}
            onChange={(event) => setActivationCode(event.target.value)}
            placeholder="粘贴服务器签发的激活码"
          />

          <label htmlFor="device-label">设备名称</label>
          <input
            id="device-label"
            name="device-label"
            autoComplete="off"
            value={deviceLabel}
            maxLength={128}
            disabled={submitting}
            onChange={(event) => setDeviceLabel(event.target.value)}
          />

          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button type="submit" disabled={submitting || !activationCode.trim()}>
            {submitting ? <LoaderCircle className="spin" aria-hidden="true" size={19} /> : null}
            {submitting ? '正在激活' : '激活并进入今日学习'}
          </button>
        </form>
      </section>

      <p className="security-note">
        <ShieldCheck aria-hidden="true" size={18} />
        激活码仅使用一次，学习数据保存在你的私人服务器。
      </p>
    </main>
  )
}
