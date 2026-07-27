/* eslint-disable react-refresh/only-export-components */
import { ArrowLeft, LoaderCircle, RotateCcw } from 'lucide-react'

export function PageHeader({ title, eyebrow, back }: { title: string; eyebrow: string; back?: string }) {
  return (
    <header className="page-titlebar">
      {back ? (
        <a className="icon-link" href={'#' + back} aria-label="返回">
          <ArrowLeft aria-hidden="true" size={22} />
        </a>
      ) : null}
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
      </div>
    </header>
  )
}

export function LoadingState({ label = '正在加载' }: { label?: string }) {
  return (
    <section className="async-state" aria-busy="true">
      <LoaderCircle className="spin" aria-hidden="true" size={26} />
      <p>{label}</p>
    </section>
  )
}

export function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <section className="async-state">
      <h2>{title}</h2>
      <p>{message}</p>
    </section>
  )
}

export function ErrorState({ message, retry }: { message: string; retry: () => void }) {
  return (
    <section className="async-state" role="alert">
      <h2>暂时无法加载</h2>
      <p>{message}</p>
      <button className="secondary-button" type="button" onClick={retry}>
        <RotateCcw aria-hidden="true" size={17} />重试
      </button>
    </section>
  )
}

export function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}
