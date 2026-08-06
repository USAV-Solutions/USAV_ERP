import React from 'react'
import { Box, Typography, Paper, Alert, Divider } from '@mui/material'
import VariantSearchAutocomplete from '../common/VariantSearchAutocomplete'
import ProductThumbnail from '../inventory/ProductThumbnail'
import { VariantSearchResult } from '../../types/orders'
import { useQuery } from '@tanstack/react-query'
import axiosClient from '../../api/axiosClient'

interface SkuSelectionStepProps {
  selectedVariant: VariantSearchResult | null
  onVariantSelect: (variant: VariantSearchResult | null) => void
}

export default function SkuSelectionStep({ selectedVariant, onVariantSelect }: SkuSelectionStepProps) {
  // Check if this variant already has active listings
  const { data: existingListings = [] } = useQuery({
    queryKey: ['variant-listings', selectedVariant?.id],
    queryFn: async () => {
      if (!selectedVariant) return []
      const { data } = await axiosClient.get(`/variants/${selectedVariant.id}`)
      return data.listings || []
    },
    enabled: !!selectedVariant,
  })

  const hasEbayListings = existingListings.some((l: any) => l.platform.startsWith('EBAY_'))

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 3 }}>
        Step 1: Select Product
      </Typography>

      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Search for the SKU you want to list. All known product details will be auto-filled.
        </Typography>

        <VariantSearchAutocomplete
          value={selectedVariant}
          onChange={onVariantSelect}
          width="100%"
          label="Search SKU or Product Name"
        />
      </Paper>

      {selectedVariant && (
        <Paper sx={{ p: 3 }}>
          <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 'bold' }}>
            Selected Product Overview
          </Typography>
          
          <Box sx={{ display: 'flex', gap: 3 }}>
            <Box sx={{ width: 120, flexShrink: 0 }}>
              <ProductThumbnail sku={selectedVariant.full_sku} size={120} />
            </Box>
            
            <Box sx={{ flexGrow: 1 }}>
              <Typography variant="h6">{selectedVariant.variant_name || selectedVariant.product_name}</Typography>
              <Typography variant="body1" fontFamily="monospace" sx={{ mb: 1 }}>
                SKU: {selectedVariant.full_sku}
              </Typography>
              
              <Divider sx={{ my: 1 }} />
              
              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mt: 2 }}>
                <Box>
                  <Typography variant="caption" color="text.secondary">Condition</Typography>
                  <Typography variant="body2">{selectedVariant.condition_code === 'N' ? 'New' : selectedVariant.condition_code === 'R' ? 'Refurbished' : 'Used'}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Color</Typography>
                  <Typography variant="body2">{selectedVariant.color_code || 'N/A'}</Typography>
                </Box>
              </Box>
            </Box>
          </Box>

          {hasEbayListings && (
            <Alert severity="warning" sx={{ mt: 3 }}>
              This SKU already has active eBay listings. Creating a new listing might result in duplicates if you don't choose a different eBay store account.
            </Alert>
          )}
        </Paper>
      )}
    </Box>
  )
}
