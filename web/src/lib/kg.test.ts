import { describe, expect, it } from 'vitest'
import { asPercent, filterGraph, graphMatchMetrics, groupConnections, isEstimate, methodPhrase, noFilters, searchNodes, nodeRadius, type KgStats } from './kg'
import { mockGraph } from './kg-mock'

describe('kg helpers', () => {
  const graph = mockGraph('p')
  it('reads percentages given as a fraction or a percent', () => {
    expect(asPercent(0.6)).toBe(60)
    expect(asPercent(60)).toBe(60)
    expect(asPercent(null)).toBeNull()
  })
  it('calls edges below 0.6 estimates', () => {
    const estimate = graph.edges.find((edge) => edge.confidence < 0.6)
    const solid = graph.edges.find((edge) => edge.confidence >= 0.6)
    expect(estimate && isEstimate(estimate)).toBe(true)
    expect(solid && isEstimate(solid)).toBe(false)
  })
  it('describes a position match in plain words', () => {
    const edge = graph.edges.find((item) => item.method === 'position')
    expect(edge && methodPhrase(edge)).toMatch(/matched by position/)
  })
  it('finds items by label', () => {
    expect(searchNodes(graph.nodes, 'kitchen').length).toBeGreaterThan(0)
    expect(searchNodes(graph.nodes, 'zzzz-nothing')).toEqual([])
  })
  it('keeps everything with no filters and fewer items with a level', () => {
    const all = filterGraph(graph.nodes, graph.edges, noFilters())
    expect(all.nodes.length).toBe(graph.nodes.length)
    const level = filterGraph(graph.nodes, graph.edges, { ...noFilters(), level: 'Level 2' })
    expect(level.nodes.length).toBeLessThan(all.nodes.length)
    const ids = new Set(level.nodes.map((node) => node.id))
    expect(level.edges.every((edge) => ids.has(edge.from) && ids.has(edge.to))).toBe(true)
  })
  it('groups connections by edge kind and grows nodes with degree', () => {
    const node = graph.nodes.find((item) => item.label === 'Kitchen' && item.kind === 'room')!
    const rows = graph.edges.filter((edge) => edge.from === node.id || edge.to === node.id).map((edge) => ({ edge, node: graph.nodes.find((n) => n.id === (edge.from === node.id ? edge.to : edge.from))!, outgoing: edge.from === node.id }))
    const groups = groupConnections(rows)
    expect(groups.length).toBeGreaterThan(0)
    expect(nodeRadius(20, 'room')).toBeGreaterThan(nodeRadius(1, 'room'))
  })
})

describe('graph match totals', () => {
  const empty: KgStats = { nodes: 0, edges: 0, linked_pct: null, agree_pct: null, unlinked: [], issues: 0 }
  it('explains zero matches and zero comparisons instead of showing dashes or claiming disagreement', () => {
    const result = graphMatchMetrics({ ...empty, nodes: 100, edges: 80, edges_by_kind: { contains: 80 } })
    expect(result.linked).toEqual({ value: '0', hint: 'No items have been matched across files yet.' })
    expect(result.agree).toEqual({ value: '0', hint: 'No values have been compared between files yet.' })
  })
  it('uses full-project item and edge counts when the API percentages are absent', () => {
    const result = graphMatchMetrics({ ...empty, counterpart_items: 200, linked_items: 60, edges_by_kind: { same_as: 40, agrees: 3, differs: 1 } })
    expect(result.linked.value).toBe('30%')
    expect(result.agree.value).toBe('75%')
  })
  it('shows recorded matching links without guessing an item percentage', () => {
    const result = graphMatchMetrics({ ...empty, edges_by_kind: { same_as: 12 } })
    expect(result.linked.value).toBe('12')
    expect(result.linked.hint).toContain('share of matched items is not available')
  })
  it('preserves recorded percentages including zero and percentages below one', () => {
    const result = graphMatchMetrics({ ...empty, linked_pct: 0.6, agree_pct: 0, edges_by_kind: { agrees: 3 } })
    expect(result.linked.value).toBe('0.6%')
    expect(result.agree.value).toBe('0%')
    expect(result.agree.hint).toBe('Compared values that agree between files')
  })
})
