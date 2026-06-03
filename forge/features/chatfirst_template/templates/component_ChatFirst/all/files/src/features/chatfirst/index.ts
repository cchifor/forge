export const chatfirstRoutes = [
  {
    path: '',
    name: 'chatfirst-results',
    component: () => import('./ui/ResultsPage.vue'),
    meta: { title: 'Results' },
  },
]
