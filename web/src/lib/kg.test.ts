import { describe, expect, it } from 'vitest'
import { asPercent, filterGraph, groupConnections, isEstimate, methodPhrase, noFilters, searchNodes, nodeRadius } from './kg'
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
