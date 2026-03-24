import axiosClient from './axiosClient'
import { CATALOG } from './endpoints'
import type { FamilySearchResult, IdentitySearchResult, ProductType } from '../types/inventory'

interface PaginatedResponse<T> {
  items: T[]
  total: number
  skip: number
  limit: number
}

interface SearchIdentityParams {
  limit?: number
  includeTypes?: ProductType[]
  excludeTypes?: ProductType[]
}

export async function searchIdentityOptions(
  query: string,
  params: SearchIdentityParams = {},
): Promise<IdentitySearchResult[]> {
  const payload: Record<string, string | number> = {
    q: query,
    limit: params.limit ?? 20,
  }

  if (params.includeTypes?.length) {
    payload.include_types = params.includeTypes.join(',')
  }
  if (params.excludeTypes?.length) {
    payload.exclude_types = params.excludeTypes.join(',')
  }

  const { data } = await axiosClient.get<IdentitySearchResult[]>(CATALOG.IDENTITY_SEARCH, {
    params: payload,
  })
  return data
}

export async function searchFamilyOptions(query: string, limit = 20): Promise<FamilySearchResult[]> {
  const { data } = await axiosClient.get<PaginatedResponse<FamilySearchResult>>(CATALOG.FAMILIES, {
    params: {
      search: query,
      limit,
    },
  })
  return data.items || []
}
