import React, { useState } from 'react'
import {
  Box,
  Typography,
  Paper,
  Grid,
  Button,
  CircularProgress,
  ImageList,
  ImageListItem,
  ImageListItemBar,
  Checkbox,
  Divider,
} from '@mui/material'
import { CloudUpload as CloudUploadIcon, Publish as PublishIcon, Save as SaveIcon } from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axiosClient from '../../api/axiosClient'
import { IMAGES } from '../../api/endpoints'
import { EbayListingDraft } from '../../types/ebayListing'

interface PreviewPublishStepProps {
  draft: EbayListingDraft
  onChange: (draft: Partial<EbayListingDraft>) => void
  onSaveDraft: () => void
  onPublish: () => void
  isPublishing: boolean
  isSaving: boolean
}

export default function PreviewPublishStep({
  draft,
  onChange,
  onSaveDraft,
  onPublish,
  isPublishing,
  isSaving,
}: PreviewPublishStepProps) {
  const queryClient = useQueryClient()
  const [uploading, setUploading] = useState(false)

  // Fetch existing images for this SKU
  const { data: imagesData, isLoading: isLoadingImages } = useQuery({
    queryKey: ['sku-images', draft.sku],
    queryFn: async () => {
      if (!draft.sku) return { images: [] }
      const { data } = await axiosClient.get(IMAGES.SKU_IMAGES(draft.sku))
      return data
    },
    enabled: !!draft.sku,
  })

  const availableImages: { url: string; filename: string }[] = imagesData?.images || []

  // Initialize selectedImageUrls if empty but we have images
  React.useEffect(() => {
    if (availableImages.length > 0 && draft.selectedImageUrls.length === 0) {
      onChange({ selectedImageUrls: availableImages.map(img => img.url) })
    }
  }, [availableImages, draft.selectedImageUrls, onChange])

  const handleToggleImage = (url: string) => {
    const selected = [...draft.selectedImageUrls]
    const idx = selected.indexOf(url)
    if (idx >= 0) {
      selected.splice(idx, 1)
    } else {
      selected.push(url)
    }
    onChange({ selectedImageUrls: selected })
  }

  const uploadMutation = useMutation({
    mutationFn: async (files: FileList) => {
      const formData = new FormData()
      Array.from(files).forEach((file) => formData.append('files', file))
      await axiosClient.post(IMAGES.UPLOAD(draft.sku), formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    onMutate: () => setUploading(true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sku-images', draft.sku] })
    },
    onSettled: () => setUploading(false),
  })

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 3 }}>
        Step 3: Preview & Images
      </Typography>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 3, mb: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Typography variant="subtitle1" fontWeight="bold">Listing Images</Typography>
              <Button
                component="label"
                variant="outlined"
                size="small"
                startIcon={uploading ? <CircularProgress size={16} /> : <CloudUploadIcon />}
                disabled={uploading}
              >
                Upload
                <input
                  type="file"
                  hidden
                  multiple
                  accept="image/jpeg,image/png,image/webp"
                  onChange={(e) => {
                    if (e.target.files?.length) uploadMutation.mutate(e.target.files)
                    e.target.value = ''
                  }}
                />
              </Button>
            </Box>

            {isLoadingImages ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}><CircularProgress /></Box>
            ) : availableImages.length === 0 ? (
              <Typography color="text.secondary" sx={{ p: 2, textAlign: 'center' }}>
                No images available for this SKU. Please upload images.
              </Typography>
            ) : (
              <ImageList cols={3} gap={8}>
                {availableImages.map((img) => {
                  const isSelected = draft.selectedImageUrls.includes(img.url)
                  return (
                    <ImageListItem key={img.url} sx={{ border: isSelected ? '2px solid #1976d2' : '2px solid transparent' }}>
                      <img
                        src={`${img.url}?w=164&h=164&fit=crop&auto=format`}
                        alt={img.filename}
                        loading="lazy"
                        style={{ cursor: 'pointer' }}
                        onClick={() => handleToggleImage(img.url)}
                      />
                      <ImageListItemBar
                        sx={{
                          background:
                            'linear-gradient(to bottom, rgba(0,0,0,0.7) 0%, rgba(0,0,0,0.3) 70%, rgba(0,0,0,0) 100%)',
                        }}
                        position="top"
                        actionIcon={
                          <Checkbox
                            checked={isSelected}
                            onChange={() => handleToggleImage(img.url)}
                            sx={{ color: 'white', '&.Mui-checked': { color: '#1976d2' } }}
                          />
                        }
                        actionPosition="left"
                      />
                    </ImageListItem>
                  )
                })}
              </ImageList>
            )}
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
              {draft.selectedImageUrls.length} image(s) selected for listing. The first selected image will be the primary photo.
            </Typography>
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="subtitle1" fontWeight="bold" sx={{ mb: 2 }}>Listing Summary</Typography>
            
            <Box sx={{ bgcolor: 'grey.50', p: 2, borderRadius: 1, mb: 3 }}>
              <Typography variant="subtitle2" color="primary">{draft.title}</Typography>
              <Typography variant="h5" sx={{ mt: 1 }}>${draft.price.toFixed(2)}</Typography>
              
              <Divider sx={{ my: 1.5 }} />
              
              <Grid container spacing={1}>
                <Grid item xs={4}><Typography variant="body2" color="text.secondary">Store Account</Typography></Grid>
                <Grid item xs={8}><Typography variant="body2" fontWeight="medium">{draft.storeId.toUpperCase()}</Typography></Grid>
                
                <Grid item xs={4}><Typography variant="body2" color="text.secondary">Quantity</Typography></Grid>
                <Grid item xs={8}><Typography variant="body2">{draft.quantity}</Typography></Grid>
                
                <Grid item xs={4}><Typography variant="body2" color="text.secondary">Condition</Typography></Grid>
                <Grid item xs={8}><Typography variant="body2">{draft.conditionId}</Typography></Grid>
                
                <Grid item xs={4}><Typography variant="body2" color="text.secondary">Category</Typography></Grid>
                <Grid item xs={8}><Typography variant="body2">{draft.categoryPath}</Typography></Grid>
                
                <Grid item xs={4}><Typography variant="body2" color="text.secondary">Weight</Typography></Grid>
                <Grid item xs={8}><Typography variant="body2">{draft.weightLbs} lbs {draft.weightOz} oz</Typography></Grid>
                
                <Grid item xs={4}><Typography variant="body2" color="text.secondary">Policies</Typography></Grid>
                <Grid item xs={8}>
                  <Typography variant="body2">
                    {draft.isFreeShipping ? 'Free Shipping' : 'Calculated Shipping'} · 
                    {draft.useNoReturnsPolicy ? ' No Returns' : ' Accepts Returns'}
                  </Typography>
                </Grid>
              </Grid>
            </Box>

            <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
              <Button
                variant="outlined"
                color="inherit"
                startIcon={<SaveIcon />}
                onClick={onSaveDraft}
                disabled={isSaving || isPublishing}
              >
                {isSaving ? 'Saving...' : 'Save Draft'}
              </Button>
              <Button
                variant="contained"
                color="primary"
                startIcon={<PublishIcon />}
                onClick={onPublish}
                disabled={isSaving || isPublishing || !draft.title || draft.selectedImageUrls.length === 0}
              >
                {isPublishing ? 'Publishing...' : 'Publish to eBay'}
              </Button>
            </Box>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  )
}
