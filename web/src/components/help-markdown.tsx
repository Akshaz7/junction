import { Fragment, type ReactNode } from 'react'

// React escapes every text node. HTML and images are deliberately plain text;
// links only accept web URLs, mail addresses, and local navigation.
function safeHref(value: string): string | undefined {
  const href = value.trim()
  if (/[\s\u0000-\u001f\u007f\\]/.test(href)) return undefined
  if (/^(?:https?:\/\/|mailto:)/i.test(href) || href.startsWith('#') || /^\/(?!\/)/.test(href)) return href
  return undefined
}

function inline(text: string): ReactNode[] {
  const tokens = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\([^\s)]+\))/g
  const nodes: ReactNode[] = []
  let cursor = 0
  for (const match of text.matchAll(tokens)) {
    const token = match[0]
    const index = match.index!
    nodes.push(text.slice(cursor, index))
    let content: ReactNode = token
    if (token.startsWith('`')) content = <code>{token.slice(1, -1)}</code>
    else if (token.startsWith('**')) content = <strong>{inline(token.slice(2, -2))}</strong>
    else if (token.startsWith('*')) content = <em>{inline(token.slice(1, -1))}</em>
    else {
      const link = /^\[([^\]]+)\]\((.+)\)$/.exec(token)!
      const href = safeHref(link[2])
      content = href ? <a href={href}>{inline(link[1])}</a> : link[1]
    }
    nodes.push(<Fragment key={index}>{content}</Fragment>)
    cursor = index + token.length
  }
  nodes.push(text.slice(cursor))
  return nodes
}

const listItem = /^\s*(?:(\d+)\.|([-+*]))\s+(.+)$/
const startsBlock = (line: string) => /^(?:#{1,6}\s|```|>\s?)/.test(line) || listItem.test(line)

/** Small Markdown subset for the public guide, without HTML injection. */
export function HelpMarkdown({ markdown }: { markdown: string }) {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const key = i
    const line = lines[i]
    if (!line.trim()) { i++; continue }
    if (line.startsWith('```')) {
      const code: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++])
      if (i < lines.length) i++
      blocks.push(<pre key={key}><code>{code.join('\n')}</code></pre>)
      continue
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line)
    if (heading) {
      const Tag = `h${heading[1].length}` as 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6'
      blocks.push(<Tag key={key}>{inline(heading[2])}</Tag>)
      i++
      continue
    }
    const first = listItem.exec(line)
    if (first) {
      const ordered = !!first[1]
      const items: ReactNode[] = []
      while (i < lines.length) {
        const match = listItem.exec(lines[i])
        if (!match || !!match[1] !== ordered) break
        items.push(<li key={i}>{inline(match[3])}</li>)
        i++
      }
      blocks.push(ordered ? <ol key={key} start={Number(first[1])}>{items}</ol> : <ul key={key}>{items}</ul>)
      continue
    }
    if (line.startsWith('>')) {
      const quote: string[] = []
      while (i < lines.length && lines[i].startsWith('>')) quote.push(lines[i++].replace(/^>\s?/, ''))
      blocks.push(<blockquote key={key}>{inline(quote.join(' '))}</blockquote>)
      continue
    }
    const paragraph = [line]
    i++
    while (i < lines.length && lines[i].trim() && !startsBlock(lines[i])) paragraph.push(lines[i++])
    blocks.push(<p key={key}>{inline(paragraph.join(' '))}</p>)
  }
  return <>{blocks}</>
}
