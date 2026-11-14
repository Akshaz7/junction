import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { ExportAnswerButton } from './answer-export'
import { demoDocument, makeDemoAnswer } from '../mock/handler'

it('exposes a standalone export button the lead can mount without opening a dialog on render', () => {
  const html = renderToStaticMarkup(createElement(ExportAnswerButton, { answer: makeDemoAnswer('How many windows are there?'), docs: [demoDocument], chatId: 'chat-1' }))
  expect(html).toContain('type="button"')
  expect(html).toContain('Export report')
  expect(html).not.toContain('<dialog')
  expect(html).not.toContain('<iframe')
})
