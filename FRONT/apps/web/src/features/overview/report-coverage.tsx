import type { FunnelLoadProgress, FunnelReport } from '@app/api'

export function ReportCoverage({
  reports,
  progress = [],
  historyNotice
}: {
  reports: (FunnelReport | undefined)[]
  progress?: (FunnelLoadProgress | undefined)[]
  historyNotice?: string
}) {
  const liveReports = reports.map((report, index) =>
    report && progress[index] ? { ...report, ...progress[index] } : report
  )
  const pending = liveReports.filter(report => report?.is_loading)
  const daysPending = pending.filter(
    report =>
      report!.known_days < (report!.available_days ?? report!.period_days)
  )
  const loaded = daysPending.reduce(
    (sum, report) =>
      sum +
      Math.min(
        report!.known_days,
        report!.available_days ?? report!.period_days
      ),
    0
  )
  const total = daysPending.reduce(
    (sum, report) => sum + (report!.available_days ?? report!.period_days),
    0
  )
  return (
    <div
      className='report-coverage'
      role='status'
    >
      {daysPending.length > 0 && (
        <>
          <progress
            aria-label='Загрузка истории продаж'
            max={Math.max(1, total)}
            value={loaded}
          />
          <span>
            Загружено {loaded} из {total} дней
          </span>
        </>
      )}
      {pending.length > 0 && daysPending.length === 0 && (
        <span>Обновляем суммы и воронку…</span>
      )}
      {progress.some(
        item => item?.is_loading && item.records_processed > 0
      ) && (
        <span>
          Текущий пакет:{' '}
          {progress
            .reduce((sum, item) => sum + (item?.records_processed ?? 0), 0)
            .toLocaleString('ru-RU')}{' '}
          записей
        </span>
      )}
      {historyNotice && (
        <span className='report-history-notice'>{historyNotice}</span>
      )}
      {reports.some(
        report =>
          report?.data_source === 'ozon_postings' &&
          report.traffic_known_days != null &&
          report.traffic_known_days < report.period_days
      ) && <span>Воронка Ozon загружается отдельно</span>}
    </div>
  )
}
