import React, { useState } from 'react'
import {
  Box,
  Typography,
  Stepper,
  Step,
  StepLabel,
  Button,
  Snackbar,
  Alert,
} from '@mui/material'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import SkuSelectionStep from '../components/listings/SkuSelectionStep'
import ListingDetailsStep from '../components/listings/ListingDetailsStep'
import PreviewPublishStep from '../components/listings/PreviewPublishStep'
import { EbayListingDraft } from '../types/ebayListing'
import { publishEbayListing } from '../api/ebayListing'
import { VariantSearchResult } from '../types/orders'

const steps = ['Select Product', 'Listing Details', 'Preview & Publish']

const initialDraft: EbayListingDraft = {
  variantId: 0,
  sku: '',
  storeId: 'usav',
  title: '',
  description: '',
  price: 0,
  quantity: 1,
  conditionId: '3000', // Default to Used
  categoryId: '',
  categoryPath: '',
  aspects: [],
  weightLbs: 0,
  weightOz: 0,
  packageLength: 0,
  packageWidth: 0,
  packageHeight: 0,
  isFreeShipping: false,
  useNoReturnsPolicy: false,
  selectedImageUrls: [],
}

export default function CreateEbayListing() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  
  const [activeStep, setActiveStep] = useState(0)
  const [selectedVariant, setSelectedVariant] = useState<VariantSearchResult | null>(null)
  const [draft, setDraft] = useState<EbayListingDraft>(initialDraft)
  
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const handleNext = () => {
    // Validation
    if (activeStep === 0 && !selectedVariant) {
      setErrorMsg('Please select a product variant first.')
      return
    }
    if (activeStep === 1) {
      if (!draft.storeId) {
        setErrorMsg('Please select an eBay store account.')
        return
      }
      if (!draft.title) {
        setErrorMsg('Listing title is required.')
        return
      }
      if (!draft.categoryId) {
        setErrorMsg('eBay category is required.')
        return
      }
      if (draft.price <= 0) {
        setErrorMsg('Price must be greater than 0.')
        return
      }
    }
    setActiveStep((prev) => prev + 1)
  }

  const handleBack = () => setActiveStep((prev) => prev - 1)

  const handleVariantSelect = (variant: VariantSearchResult | null) => {
    setSelectedVariant(variant)
    if (variant) {
      // Auto-populate draft with known info
      const basePrice = (variant as any).cost_basis || 0 // fallback if cost basis not joined
      // Charm pricing logic
      const targetPrice = basePrice > 0 ? basePrice * 1.05 : 0
      let charmPrice = 0
      if (targetPrice > 0) {
        const wholeStr = Math.floor(targetPrice).toString()
        const endsIn0or5 = wholeStr.endsWith('0') || wholeStr.endsWith('5')
        charmPrice = parseFloat(`${Math.floor(targetPrice)}.${endsIn0or5 ? '88' : '68'}`)
      }

      setDraft((prev) => ({
        ...prev,
        variantId: variant.id,
        sku: variant.full_sku,
        title: variant.variant_name || variant.product_name || '',
        price: charmPrice,
        conditionId: variant.condition_code === 'N' ? '1000' : variant.condition_code === 'R' ? '2000' : '3000',
        // Try to get dimensions and weight from identity if passed
        weightLbs: (variant as any).identity?.weight ? Math.floor((variant as any).identity.weight) : 0,
        weightOz: (variant as any).identity?.weight ? Math.round(((variant as any).identity.weight % 1) * 16) : 0,
        packageLength: (variant as any).identity?.dimension_length || 0,
        packageWidth: (variant as any).identity?.dimension_width || 0,
        packageHeight: (variant as any).identity?.dimension_height || 0,
        // Auto-fill brand if available
        aspects: (variant as any).brand ? [{ name: 'Brand', values: [(variant as any).brand], required: false }] : [],
      }))
    }
  }

  const publishMutation = useMutation({
    mutationFn: async () => {
      return await publishEbayListing(draft)
    },
    onSuccess: (res) => {
      setSuccessMsg(`Successfully published to eBay! Listing ID: ${res.listing_id}`)
      queryClient.invalidateQueries({ queryKey: ['listings'] })
      setTimeout(() => {
        navigate('/catalog/listings/active')
      }, 2000)
    },
    onError: (err: any) => {
      setErrorMsg(err.response?.data?.detail || err.message || 'Failed to publish listing')
    },
  })

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Create eBay Listing</Typography>
        <Button variant="outlined" onClick={() => navigate('/catalog/listings/active')}>
          Cancel
        </Button>
      </Box>

      <Snackbar open={!!errorMsg} autoHideDuration={6000} onClose={() => setErrorMsg(null)}>
        <Alert onClose={() => setErrorMsg(null)} severity="error" sx={{ width: '100%' }}>
          {errorMsg}
        </Alert>
      </Snackbar>
      
      <Snackbar open={!!successMsg} autoHideDuration={6000} onClose={() => setSuccessMsg(null)}>
        <Alert onClose={() => setSuccessMsg(null)} severity="success" sx={{ width: '100%' }}>
          {successMsg}
        </Alert>
      </Snackbar>

      <Box sx={{ width: '100%', mb: 4 }}>
        <Stepper activeStep={activeStep}>
          {steps.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>
      </Box>

      {activeStep === 0 && (
        <SkuSelectionStep
          selectedVariant={selectedVariant}
          onVariantSelect={handleVariantSelect}
        />
      )}

      {activeStep === 1 && (
        <ListingDetailsStep
          draft={draft}
          onChange={(updates) => setDraft((prev) => ({ ...prev, ...updates }))}
        />
      )}

      {activeStep === 2 && (
        <PreviewPublishStep
          draft={draft}
          onChange={(updates) => setDraft((prev) => ({ ...prev, ...updates }))}
          onSaveDraft={() => {
            // Basic save to DB implementation
            // Actually, we could implement a separate save endpoint, but for now we'll just show an info toast
            setSuccessMsg('Draft save is currently a placeholder.')
          }}
          onPublish={() => publishMutation.mutate()}
          isPublishing={publishMutation.isPending}
          isSaving={false}
        />
      )}

      <Box sx={{ display: 'flex', flexDirection: 'row', pt: 2, mt: 3 }}>
        <Button
          color="inherit"
          disabled={activeStep === 0 || publishMutation.isPending}
          onClick={handleBack}
          sx={{ mr: 1 }}
        >
          Back
        </Button>
        <Box sx={{ flex: '1 1 auto' }} />
        {activeStep < steps.length - 1 && (
          <Button onClick={handleNext} variant="contained">
            Next
          </Button>
        )}
      </Box>
    </Box>
  )
}
