import { useSyncExternalStore } from 'react'

export const routes = ['overview', 'chat', 'changes', 'data', 'accuracy', 'skills', 'automations'] as const
export type Route = typeof routes[number]

function currentRoute(): Route {
  const route = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  return routes.includes(route as Route) ? route as Route : 'chat'
}

function subscribe(onChange: () => void) {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

export function useRoute() {
  return useSyncExternalStore(subscribe, currentRoute)
}

export function navigate(route: Route) {
  window.location.hash = `/${route}`
}
