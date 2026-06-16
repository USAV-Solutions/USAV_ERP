import React, { useState } from 'react'
import {
  Box,
  Typography,
  Paper,
  Grid,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  InputAdornment,
  Checkbox,
  FormControlLabel,
  Button,
  CircularProgress,
  Autocomplete,
  Snackbar,
  Alert,
} from '@mui/material'
import { AutoAwesome as AutoAwesomeIcon } from '@mui/icons-material'
import EbayAccountSelector from './EbayAccountSelector'
import ItemSpecificsEditor from './ItemSpecificsEditor'
import { EbayListingDraft, EbayCategorySuggestion } from '../../types/ebayListing'
import {
  aiShortenTitle,
  aiGenerateDescription,
  aiSuggestDetails,
  searchEbayCategories,
  getEbayCategoryAspects,
} from '../../api/ebayListing'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import { useQuery } from '@tanstack/react-query'

interface ListingDetailsStepProps {
  draft: EbayListingDraft
  onChange: (draft: Partial<EbayListingDraft>) => void
}

export default function ListingDetailsStep({ draft, onChange }: ListingDetailsStepProps) {
  const [isShortening, setIsShortening] = useState(false)
  const [isGeneratingDesc, setIsGeneratingDesc] = useState(false)
  const [isSuggesting, setIsSuggesting] = useState(false)
  
  const [categorySearch, setCategorySearch] = useState('')
  const debouncedCategorySearch = useDebouncedValue(categorySearch, 400)
  
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const { data: categoryOptions = [], isFetching: isFetchingCategories } = useQuery({
    queryKey: ['ebay-categories', debouncedCategorySearch, draft.storeId],
    queryFn: () => searchEbayCategories(debouncedCategorySearch, draft.storeId || 'usav'),
    enabled: debouncedCategorySearch.length >= 3 && !!draft.storeId,
  })

  const handleShortenTitle = async () => {
    if (!draft.title) return
    setIsShortening(true)
    try {
      const { title } = await aiShortenTitle(draft.title)
      onChange({ title })
    } catch (e: any) {
      setErrorMsg(e.response?.data?.detail || 'Failed to shorten title')
    } finally {
      setIsShortening(false)
    }
  }

  const handleGenerateDesc = async () => {
    setIsGeneratingDesc(true)
    try {
      const { description } = await aiGenerateDescription({
        title: draft.title,
        condition: draft.conditionId === '1000' ? 'New' : draft.conditionId === '3000' ? 'Used' : 'Refurbished',
        aspects: draft.aspects,
        brand: draft.aspects.find((a) => a.name === 'Brand')?.values[0],
      })
      onChange({ description })
    } catch (e: any) {
      setErrorMsg(e.response?.data?.detail || 'Failed to generate description')
    } finally {
      setIsGeneratingDesc(false)
    }
  }

  const handleSuggestDetails = async () => {
    setIsSuggesting(true)
    try {
      const data = await aiSuggestDetails({
        title: draft.title,
        description: draft.description,
        imageUrl: draft.selectedImageUrls[0],
      })
      
      const updates: Partial<EbayListingDraft> = {}
      
      if (data.category_id) {
        updates.categoryId = data.category_id
        updates.categoryPath = data.category_name
      }
      if (data.aspects && data.aspects.length > 0) {
        // Merge suggested aspects with existing (favoring existing if they have values)
        const merged = [...draft.aspects]
        for (const suggested of data.aspects) {
          if (!merged.find(a => a.name === suggested.name)) {
            merged.push(suggested)
          }
        }
        updates.aspects = merged
      }
      if (data.weight_lbs !== undefined) updates.weightLbs = data.weight_lbs
      if (data.weight_oz !== undefined) updates.weightOz = data.weight_oz
      if (data.package_length !== undefined) updates.packageLength = data.package_length
      if (data.package_width !== undefined) updates.packageWidth = data.package_width
      if (data.package_height !== undefined) updates.packageHeight = data.package_height
      
      onChange(updates)
    } catch (e: any) {
      setErrorMsg(e.response?.data?.detail || 'Failed to suggest details')
    } finally {
      setIsSuggesting(false)
    }
  }

  const handleCategorySelect = async (cat: EbayCategorySuggestion | null) => {
    if (!cat) {
      onChange({ categoryId: '', categoryPath: '' })
      return
    }
    const path = [...cat.categoryTreeNodeAncestors.map((a) => a.categoryName), cat.categoryName].join(' > ')
    onChange({ categoryId: cat.categoryId, categoryPath: path })
    
    // Auto-fetch aspects for the new category
    try {
      const aspects = await getEbayCategoryAspects(cat.categoryId, draft.storeId || 'usav')
      const newAspects = aspects.filter((a) => a.aspectConstraint?.aspectRequired).map((a) => ({
        name: a.localizedAspectName,
        values: [],
        required: true,
      }))
      
      // Merge with existing
      const merged = [...draft.aspects]
      for (const reqAspect of newAspects) {
        if (!merged.find(a => a.name === reqAspect.name)) {
          merged.push(reqAspect)
        }
      }
      onChange({ aspects: merged })
    } catch (e) {
      // non-fatal
    }
  }

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 3 }}>
        Step 2: Listing Details
      </Typography>

      <Snackbar open={!!errorMsg} autoHideDuration={6000} onClose={() => setErrorMsg(null)}>
        <Alert onClose={() => setErrorMsg(null)} severity="error" sx={{ width: '100%' }}>
          {errorMsg}
        </Alert>
      </Snackbar>

      <Grid container spacing={3}>
        {/* Left Column */}
        <Grid item xs={12} md={7}>
          <Paper sx={{ p: 3, mb: 3 }}>
            <Box sx={{ mb: 3 }}>
              <EbayAccountSelector
                value={draft.storeId}
                onChange={(storeId) => onChange({ storeId })}
              />
            </Box>

            <Box sx={{ mb: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', mb: 1 }}>
                <Typography variant="subtitle2">Title</Typography>
                <Button
                  size="small"
                  variant="text"
                  color="secondary"
                  startIcon={isShortening ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}
                  onClick={handleShortenTitle}
                  disabled={isShortening || !draft.title}
                >
                  AI Shorten
                </Button>
              </Box>
              <TextField
                fullWidth
                size="small"
                value={draft.title}
                onChange={(e) => onChange({ title: e.target.value })}
                inputProps={{ maxLength: 80 }}
                helperText={`${draft.title.length}/80 characters`}
                error={draft.title.length > 80}
              />
            </Box>

            <Grid container spacing={2} sx={{ mb: 3 }}>
              <Grid item xs={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Price"
                  type="number"
                  value={draft.price || ''}
                  onChange={(e) => onChange({ price: parseFloat(e.target.value) || 0 })}
                  InputProps={{
                    startAdornment: <InputAdornment position="start">$</InputAdornment>,
                  }}
                />
              </Grid>
              <Grid item xs={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Quantity"
                  type="number"
                  value={draft.quantity || ''}
                  onChange={(e) => onChange({ quantity: parseInt(e.target.value, 10) || 1 })}
                />
              </Grid>
              <Grid item xs={4}>
                <FormControl fullWidth size="small">
                  <InputLabel>Condition</InputLabel>
                  <Select
                    value={draft.conditionId}
                    label="Condition"
                    onChange={(e) => onChange({ conditionId: e.target.value as string })}
                  >
                    <MenuItem value="1000">New</MenuItem>
                    <MenuItem value="1500">New other (see details)</MenuItem>
                    <MenuItem value="2000">Certified - Refurbished</MenuItem>
                    <MenuItem value="2500">Seller refurbished</MenuItem>
                    <MenuItem value="3000">Used</MenuItem>
                    <MenuItem value="7000">For parts or not working</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
            </Grid>

            <Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', mb: 1 }}>
                <Typography variant="subtitle2">Description</Typography>
                <Button
                  size="small"
                  variant="text"
                  color="secondary"
                  startIcon={isGeneratingDesc ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}
                  onClick={handleGenerateDesc}
                  disabled={isGeneratingDesc || !draft.title}
                >
                  AI Generate
                </Button>
              </Box>
              <TextField
                fullWidth
                multiline
                rows={10}
                value={draft.description}
                onChange={(e) => onChange({ description: e.target.value })}
                placeholder="Enter HTML description..."
              />
            </Box>
          </Paper>
        </Grid>

        {/* Right Column */}
        <Grid item xs={12} md={5}>
          <Paper sx={{ p: 3, mb: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Typography variant="subtitle1" fontWeight="bold">Category & specifics</Typography>
              <Button
                size="small"
                variant="outlined"
                color="secondary"
                startIcon={isSuggesting ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}
                onClick={handleSuggestDetails}
                disabled={isSuggesting || !draft.title || !draft.storeId}
              >
                AI Suggest All
              </Button>
            </Box>

            <Box sx={{ mb: 3 }}>
              <Autocomplete<EbayCategorySuggestion>
                size="small"
                options={categoryOptions}
                loading={isFetchingCategories}
                getOptionLabel={(o) => `${o.categoryName} (${o.categoryId})`}
                filterOptions={(x) => x}
                onInputChange={(e, val) => setCategorySearch(val)}
                onChange={(e, val) => handleCategorySelect(val)}
                renderInput={(params) => (
                  <TextField {...params} label="eBay Category" placeholder="Search categories..." />
                )}
                renderOption={(props, option) => {
                  const path = option.categoryTreeNodeAncestors.map((a) => a.categoryName).join(' > ')
                  return (
                    <li {...props} key={option.categoryId}>
                      <Box>
                        <Typography variant="body2">{option.categoryName}</Typography>
                        <Typography variant="caption" color="text.secondary">{path}</Typography>
                      </Box>
                    </li>
                  )
                }}
              />
              {draft.categoryPath && (
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                  Selected: {draft.categoryPath}
                </Typography>
              )}
            </Box>

            <ItemSpecificsEditor
              aspects={draft.aspects}
              onChange={(aspects) => onChange({ aspects })}
            />
          </Paper>

          <Paper sx={{ p: 3 }}>
            <Typography variant="subtitle1" fontWeight="bold" sx={{ mb: 2 }}>Package & Shipping</Typography>
            
            <Grid container spacing={2} sx={{ mb: 2 }}>
              <Grid item xs={6}>
                <TextField
                  fullWidth
                  size="small"
                  label="Weight (lbs)"
                  type="number"
                  value={draft.weightLbs || ''}
                  onChange={(e) => onChange({ weightLbs: parseInt(e.target.value, 10) || 0 })}
                />
              </Grid>
              <Grid item xs={6}>
                <TextField
                  fullWidth
                  size="small"
                  label="Weight (oz)"
                  type="number"
                  value={draft.weightOz || ''}
                  onChange={(e) => onChange({ weightOz: parseInt(e.target.value, 10) || 0 })}
                />
              </Grid>
            </Grid>
            
            <Grid container spacing={2} sx={{ mb: 3 }}>
              <Grid item xs={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Length (in)"
                  type="number"
                  value={draft.packageLength || ''}
                  onChange={(e) => onChange({ packageLength: parseInt(e.target.value, 10) || 0 })}
                />
              </Grid>
              <Grid item xs={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Width (in)"
                  type="number"
                  value={draft.packageWidth || ''}
                  onChange={(e) => onChange({ packageWidth: parseInt(e.target.value, 10) || 0 })}
                />
              </Grid>
              <Grid item xs={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Height (in)"
                  type="number"
                  value={draft.packageHeight || ''}
                  onChange={(e) => onChange({ packageHeight: parseInt(e.target.value, 10) || 0 })}
                />
              </Grid>
            </Grid>

            <Box>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={draft.isFreeShipping}
                    onChange={(e) => onChange({ isFreeShipping: e.target.checked })}
                  />
                }
                label="Offer Free Shipping"
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={draft.useNoReturnsPolicy}
                    onChange={(e) => onChange({ useNoReturnsPolicy: e.target.checked })}
                  />
                }
                label="No Returns Accepted"
              />
            </Box>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  )
}
