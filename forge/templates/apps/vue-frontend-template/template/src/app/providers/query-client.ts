import { QueryClient } from '@tanstack/vue-query'
import { toast } from 'vue-sonner'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      onError: (error) => {
        const message =
          error instanceof Error ? error.message : 'An unexpected error occurred'
        toast.error(message)
      },
    },
  },
})
