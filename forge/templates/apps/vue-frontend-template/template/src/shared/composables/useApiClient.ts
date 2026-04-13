import { type KyInstance } from 'ky'
import { getApiClient } from '@/shared/api/client'

export function useApiClient(): KyInstance {
  return getApiClient()
}
