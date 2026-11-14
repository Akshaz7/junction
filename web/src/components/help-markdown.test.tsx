import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { HelpMarkdown } from './help-markdown'

const render = (markdown: string) => renderToStaticMarkup(createElement(HelpMarkdown, { markdown }))

describe('judges’ guide Markdown', () => {
  it('renders the guide structure, emphasis, links and numbered steps', () => {
    const html = render('# Guide\n\nChoose **Data → Upload**.\n\n1. Counts: “How many windows?”\n2. Open [Chat](#/chat).\n\n## Proof\n\nRead `item_id`.\n\n- Check sources\n- Check scale\n\n> Verify the drawing.\n\n```\nwindow-001\n```')
    expect(html).toContain('<h1>Guide</h1>')
    expect(html).toContain('<strong>Data → Upload</strong>')
    expect(html).toContain('<ol start="1"><li>Counts: “How many windows?”</li>')
    expect(html).toContain('<a href="#/chat">Chat</a>')
    expect(html).toContain('<h2>Proof</h2>')
    expect(html).toContain('<code>item_id</code>')
    expect(html).toContain('<ul><li>Check sources</li><li>Check scale</li></ul>')
    expect(html).toContain('<blockquote>Verify the drawing.</blockquote>')
    expect(html).toContain('<pre><code>window-001</code></pre>')
  })

  it('escapes HTML and refuses script, data, protocol-relative and backslash links', () => {
    const html = render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[bad](javascript:alert) [bad](data:text/html,test) [bad](//evil.test) [bad](/\\evil.test) [ok](https://example.com/guide)')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;script&gt;')
    expect(html).not.toMatch(/href="(?:javascript:|data:|\/\/|\/\\)/)
    expect(html.match(/<a /g)).toHaveLength(1)
    expect(html).toContain('href="https://example.com/guide"')
  })
})
