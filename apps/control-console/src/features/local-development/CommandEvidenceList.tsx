import {
  formatDuration,
  readNumber,
  readString,
  readStringArray,
  statusTone,
  type JsonRecord,
} from './evidenceViewModel'

interface CommandEvidenceListProps {
  commands: JsonRecord[]
  emptyText: string
}

/**
 * Tester 与 Security 共用的真实命令证据列表。
 */
export function CommandEvidenceList({ commands, emptyText }: CommandEvidenceListProps) {
  if (commands.length === 0) {
    return <p className="empty-state">{emptyText}</p>
  }

  return (
    <div className="command-evidence-list">
      {commands.map((command, index) => {
        const status = readString(command, 'status')
        const argv = readStringArray(command, 'command')
        return (
          <details className="command-evidence" key={`${readString(command, 'call_id') ?? 'command'}-${index}`}>
            <summary>
              <code>{argv.length === 0 ? '命令数组未记录' : argv.join(' ')}</code>
              <span className={`evidence-status tone-${statusTone(status)}`}>
                {status ?? 'unknown'}
              </span>
            </summary>
            <dl className="command-meta">
              <div>
                <dt>用途</dt>
                <dd>{readString(command, 'purpose') ?? '未记录'}</dd>
              </div>
              <div>
                <dt>Exit code</dt>
                <dd>{readNumber(command, 'exit_code') ?? '未记录'}</dd>
              </div>
              <div>
                <dt>耗时</dt>
                <dd>{formatDuration(readNumber(command, 'duration_ms'))}</dd>
              </div>
              <div>
                <dt>错误码</dt>
                <dd>{readString(command, 'error_code') ?? '无'}</dd>
              </div>
            </dl>
            <div className="command-output-grid">
              <div>
                <h4>stdout</h4>
                <pre>{readString(command, 'stdout_summary') ?? '无 stdout 摘要。'}</pre>
              </div>
              <div>
                <h4>stderr</h4>
                <pre>{readString(command, 'stderr_summary') ?? '无 stderr 摘要。'}</pre>
              </div>
            </div>
          </details>
        )
      })}
    </div>
  )
}
