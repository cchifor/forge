// Layer-3 Console template — route table consumed by the app router.
export const consoleRoutes = [
  {
    path: 'dashboard',
    name: 'console-dashboard',
    component: () => import('./ui/DashboardPage.vue'),
    meta: { title: 'Dashboard' },
  },
]
