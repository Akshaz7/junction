/** True when a question can only be answered against a specific drawing, so it must not be sent with none attached. */
const REFERS = /\b(this|the|that|these|those)\s+(drawing|drawings|plan|plans|model|document|sheet|floor ?plan|building|room|level|storey|floor)\b/i
const MEASURES = /\b(how many|count (?:the|all)?|where (?:is|are)|area of|on level \d+|which room|how (?:big|large|wide|tall|long)|list (?:the|all)|show me (?:the|all))\b/i
const GENERAL = /\b(what can you do|how do i|how can i|help me (?:upload|use)|upload (?:a |my )?files?|who are you|what is stoa)\b/i

export function needsDocument(question: string): boolean {
  const text = question.trim()
  if (!text || GENERAL.test(text)) return false
  return REFERS.test(text) || MEASURES.test(text)
}
