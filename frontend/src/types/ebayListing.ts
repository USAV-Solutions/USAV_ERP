import { Platform } from './inventory'

export interface EbayAspectValue {
  name: string
  values: string[]
  required?: boolean
}

export interface EbayListingDraft {
  // Step 1 data
  variantId: number
  sku: string
  // Step 2 data
  storeId: string  // 'usav' | 'mekong' | 'dragon'
  title: string
  description: string
  price: number
  quantity: number
  conditionId: string
  categoryId: string
  categoryPath?: string
  aspects: EbayAspectValue[]
  weightLbs: number
  weightOz: number
  packageLength: number
  packageWidth: number
  packageHeight: number
  isFreeShipping: boolean
  useNoReturnsPolicy: boolean
  upc?: string
  // Step 3 data
  selectedImageUrls: string[]
}

export interface EbayAccountInfo {
  id: string
  name: string
  merchant_location_key?: string
  payment_policy_id?: string
  return_policy_id?: string
  return_policy_id_no_returns?: string
  fulfillment_policy_id_light?: string
  fulfillment_policy_id_heavy?: string
  fulfillment_policy_id_free?: string
  heavy_item_threshold_lbs?: string
}

export interface EbayCategorySuggestion {
  categoryId: string
  categoryName: string
  categoryTreeNodeLevel: number
  categoryTreeNodeAncestors: { categoryId: string; categoryName: string }[]
}

export interface EbayCategoryAspect {
  localizedAspectName: string
  aspectConstraint: any
  aspectValues: { value: string }[]
}

export interface EbayCategoryCondition {
  conditionId: string
  conditionDescription: string
}

export interface EbayPublishResponse {
  listing_id: string
  success: boolean
  message?: string
}
