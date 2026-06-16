import axiosClient from './axiosClient'
import { EBAY_LISTING } from './endpoints'
import {
  EbayAccountInfo,
  EbayCategorySuggestion,
  EbayCategoryAspect,
  EbayCategoryCondition,
  EbayPublishResponse,
  EbayListingDraft,
  EbayAspectValue,
} from '../types/ebayListing'

export const getEbayAccounts = async (): Promise<EbayAccountInfo[]> => {
  const { data } = await axiosClient.get(EBAY_LISTING.ACCOUNTS)
  return data
}

export const searchEbayCategories = async (q: string, store: string): Promise<EbayCategorySuggestion[]> => {
  const { data } = await axiosClient.get(EBAY_LISTING.CATEGORY_SUGGESTIONS, { params: { q, store } })
  return data
}

export const getEbayCategoryAspects = async (categoryId: string, store: string): Promise<EbayCategoryAspect[]> => {
  const { data } = await axiosClient.get(EBAY_LISTING.CATEGORY_ASPECTS(categoryId), { params: { store } })
  return data
}

export const getEbayCategoryConditions = async (categoryId: string, store: string): Promise<EbayCategoryCondition[]> => {
  const { data } = await axiosClient.get(EBAY_LISTING.VALID_CONDITIONS(categoryId), { params: { store } })
  return data
}

export const aiShortenTitle = async (title: string): Promise<{ title: string }> => {
  const { data } = await axiosClient.post(EBAY_LISTING.AI_SHORTEN_TITLE, { title })
  return data
}

export const aiGenerateDescription = async (payload: {
  title: string
  condition: string
  aspects: EbayAspectValue[]
  brand?: string
}): Promise<{ description: string }> => {
  const { data } = await axiosClient.post(EBAY_LISTING.AI_GENERATE_DESC, payload)
  return data
}

export const aiSuggestDetails = async (payload: {
  title: string
  description?: string
  imageUrl?: string
}): Promise<{
  category_id?: string
  category_name?: string
  title?: string
  aspects: EbayAspectValue[]
  weight_lbs?: number
  weight_oz?: number
  package_length?: number
  package_width?: number
  package_height?: number
}> => {
  const { data } = await axiosClient.post(EBAY_LISTING.AI_SUGGEST_DETAILS, payload)
  return data
}

export const publishEbayListing = async (payload: Omit<EbayListingDraft, 'sku'>): Promise<EbayPublishResponse> => {
  const { data } = await axiosClient.post(EBAY_LISTING.PUBLISH, {
    variant_id: payload.variantId,
    store_id: payload.storeId,
    title: payload.title,
    description: payload.description,
    price: payload.price,
    quantity: payload.quantity,
    condition_id: payload.conditionId,
    category_id: payload.categoryId,
    aspects: payload.aspects,
    weight_lbs: payload.weightLbs,
    weight_oz: payload.weightOz,
    package_length: payload.packageLength,
    package_width: payload.packageWidth,
    package_height: payload.packageHeight,
    is_free_shipping: payload.isFreeShipping,
    use_no_returns_policy: payload.useNoReturnsPolicy,
    upc: payload.upc,
    selected_image_urls: payload.selectedImageUrls,
  })
  return data
}
