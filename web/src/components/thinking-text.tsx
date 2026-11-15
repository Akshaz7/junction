export function ThinkingText({ text }: { text: string }) {
  const split = text.indexOf(':')
  const verb = split < 0 ? text : text.slice(0, split + 1)
  const detail = split < 0 ? '' : text.slice(split + 1)
  return <span className="thinking-text" data-text={text}>
    <span className="thinking-verb">{verb}</span>{detail}
  </span>
}
