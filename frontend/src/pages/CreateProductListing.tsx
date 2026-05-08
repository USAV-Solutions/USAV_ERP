import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Divider,
  FormControlLabel,
  Grid,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import { useNavigate } from 'react-router-dom'
import axiosClient from '../api/axiosClient'
import { CATALOG, LISTINGS } from '../api/endpoints'
import { Platform, Variant } from '../types/inventory'

type WizardStep = 0 | 1 | 2 | 3

type DestinationKey = 'EBAY_MEKONG' | 'EBAY_USAV' | 'EBAY_DRAGON' | 'WALMART' | 'ECWID'

type SelectedDestinations = Record<DestinationKey, boolean>

interface EbayDraftResponse {
  platform: Platform
  variant_id: number
  title: string
  description: string
  sku: string
  quantity: number
  price: number
  condition_text: string | null
  upc: string | null
  brand: string | null
  color: string | null
  category_id: string | null
  picture_urls: string[]
  dimensions: {
    length: number | null
    width: number | null
    height: number | null
    weight: number | null
  }
  seller_profiles: {
    payment_profile_id: string
    return_profile_id: string
    shipping_profile_id: string
  }
}

interface EbayCategorySuggestion {
  category_id: string
  category_name: string
  category_tree_tokens: string[]
}

interface EbayCategorySuggestionsResponse {
  suggestions: EbayCategorySuggestion[]
}

interface EbayPublishResponse {
  listing_id: number
  item_id: string
  sync_status: string
}

interface EbaySpecific {
  condition_text: string
  shipping_policy_id: string
  length: string
  width: string
  height: string
  weight: string
  price_override: string
  category_id: string
  suggested_categories: EbayCategorySuggestion[]
  picture_urls: string[]
  upc: string
  brand: string
  color: string
}

interface WizardState {
  destinations: SelectedDestinations
  variant_id: number | null
  master_title: string
  master_sku: string
  base_price: string
  global_quantity: string
  description: string
  ebay: EbaySpecific
}

const DESTINATION_OPTIONS: { key: DestinationKey; label: string }[] = [
  { key: 'EBAY_MEKONG', label: 'eBay Mekong' },
  { key: 'EBAY_USAV', label: 'eBay USAV' },
  { key: 'EBAY_DRAGON', label: 'eBay Dragon' },
  { key: 'WALMART', label: 'Walmart' },
  { key: 'ECWID', label: 'Ecwid' },
]

const EBAY_KEYS: DestinationKey[] = ['EBAY_MEKONG', 'EBAY_USAV', 'EBAY_DRAGON']

const INITIAL_STATE: WizardState = {
  destinations: {
    EBAY_MEKONG: false,
    EBAY_USAV: false,
    EBAY_DRAGON: false,
    WALMART: false,
    ECWID: false,
  },
  variant_id: null,
  master_title: '',
  master_sku: '',
  base_price: '',
  global_quantity: '1',
  description: '',
  ebay: {
    condition_text: 'USED',
    shipping_policy_id: '',
    length: '',
    width: '',
    height: '',
    weight: '',
    price_override: '',
    category_id: '',
    suggested_categories: [],
    picture_urls: [],
    upc: '',
    brand: '',
    color: '',
  },
}

const STEPS: string[] = ['Destination', 'Core Details', 'Platform Specifics', 'Validate & Publish']

function parseNumber(value: string): number | undefined {
  if (!value.trim()) return undefined
  const n = Number(value)
  if (Number.isNaN(n)) return undefined
  return n
}

function formatCategoryLabel(s: EbayCategorySuggestion): string {
  const path = s.category_tree_tokens?.join(' > ').trim()
  return path || s.category_name
}

export default function CreateProductListing() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [step, setStep] = useState<WizardStep>(0)
  const [state, setState] = useState<WizardState>(INITIAL_STATE)
  const [activePlatformTab, setActivePlatformTab] = useState<DestinationKey>('EBAY_USAV')
  const [uiError, setUiError] = useState<string | null>(null)
  const [draftLoadedForPlatform, setDraftLoadedForPlatform] = useState<Platform | null>(null)

  const { data: variantsData = [], isLoading: variantsLoading } = useQuery({
    queryKey: ['variants-for-listing-create'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.VARIANTS, { params: { limit: 1000 } })
      return (response.data?.items || []) as Variant[]
    },
  })

  const selectedEbayPlatform = useMemo<Platform | null>(() => {
    if (state.destinations.EBAY_USAV) return 'EBAY_USAV'
    if (state.destinations.EBAY_MEKONG) return 'EBAY_MEKONG'
    if (state.destinations.EBAY_DRAGON) return 'EBAY_DRAGON'
    return null
  }, [state.destinations])

  const selectedPlatforms = useMemo<DestinationKey[]>(() => {
    return DESTINATION_OPTIONS.filter((p) => state.destinations[p.key]).map((p) => p.key)
  }, [state.destinations])

  useEffect(() => {
    if (selectedPlatforms.length > 0 && !selectedPlatforms.includes(activePlatformTab)) {
      setActivePlatformTab(selectedPlatforms[0])
    }
  }, [selectedPlatforms, activePlatformTab])

  const draftMutation = useMutation({
    mutationFn: async ({ platform, variant_id }: { platform: Platform; variant_id: number }) => {
      const response = await axiosClient.post<EbayDraftResponse>(LISTINGS.EBAY_DRAFT, { platform, variant_id })
      return response.data
    },
  })

  const categorySuggestionMutation = useMutation({
    mutationFn: async ({ platform, variant_id, title }: { platform: Platform; variant_id: number; title: string }) => {
      const response = await axiosClient.post<EbayCategorySuggestionsResponse>(LISTINGS.EBAY_CATEGORY_SUGGESTIONS, {
        platform,
        variant_id,
        title,
      })
      return response.data
    },
  })

  const publishMutation = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const response = await axiosClient.post<EbayPublishResponse>(LISTINGS.EBAY_PUBLISH, payload)
      return response.data
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['listings'] })
      navigate('/catalog/listings/active')
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      setUiError(typeof detail === 'string' ? detail : 'Publish failed. Please review eBay requirements and try again.')
    },
  })

  async function loadDraftIfNeeded(): Promise<boolean> {
    if (!selectedEbayPlatform) return true
    if (!state.variant_id) {
      setUiError('Variant is required to load eBay draft data.')
      return false
    }

    try {
      const draft = await draftMutation.mutateAsync({
        platform: selectedEbayPlatform,
        variant_id: state.variant_id,
      })
      setDraftLoadedForPlatform(selectedEbayPlatform)
      setState((prev) => ({
        ...prev,
        master_title: prev.master_title || draft.title,
        master_sku: prev.master_sku || draft.sku,
        base_price: prev.base_price || String(draft.price),
        global_quantity: prev.global_quantity || String(draft.quantity),
        description: prev.description || draft.description,
        ebay: {
          ...prev.ebay,
          condition_text: draft.condition_text || prev.ebay.condition_text || 'USED',
          shipping_policy_id: draft.seller_profiles.shipping_profile_id || prev.ebay.shipping_policy_id,
          length: prev.ebay.length || String(draft.dimensions.length ?? ''),
          width: prev.ebay.width || String(draft.dimensions.width ?? ''),
          height: prev.ebay.height || String(draft.dimensions.height ?? ''),
          weight: prev.ebay.weight || String(draft.dimensions.weight ?? ''),
          category_id: prev.ebay.category_id || draft.category_id || '',
          picture_urls: prev.ebay.picture_urls.length > 0 ? prev.ebay.picture_urls : draft.picture_urls,
          upc: prev.ebay.upc || draft.upc || '',
          brand: prev.ebay.brand || draft.brand || '',
          color: prev.ebay.color || draft.color || '',
        },
      }))
      return true
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      setUiError(typeof detail === 'string' ? detail : 'Failed to load eBay draft details.')
      return false
    }
  }

  useEffect(() => {
    const shouldLoadSuggestions =
      step === 2 &&
      activePlatformTab.startsWith('EBAY_') &&
      state.variant_id &&
      selectedEbayPlatform &&
      state.master_title.trim().length > 0

    if (!shouldLoadSuggestions) return

    categorySuggestionMutation
      .mutateAsync({
        platform: selectedEbayPlatform,
        variant_id: state.variant_id!,
        title: state.master_title,
      })
      .then((response) => {
        setState((prev) => {
          const first = response.suggestions[0]
          return {
            ...prev,
            ebay: {
              ...prev.ebay,
              suggested_categories: response.suggestions,
              category_id: prev.ebay.category_id || first?.category_id || '',
            },
          }
        })
      })
      .catch(() => {
        // non-blocking; user can still enter category manually
      })
  }, [step, activePlatformTab, state.variant_id, state.master_title, selectedEbayPlatform])

  const stepValid = useMemo(() => {
    if (step === 0) return selectedPlatforms.length > 0
    if (step === 1) {
      return (
        state.variant_id !== null &&
        state.master_title.trim().length > 0 &&
        state.master_sku.trim().length > 0 &&
        state.base_price.trim().length > 0 &&
        state.global_quantity.trim().length > 0 &&
        state.description.trim().length > 0
      )
    }
    if (step === 2) {
      if (!selectedEbayPlatform) return true
      return (
        state.ebay.condition_text.trim().length > 0 &&
        state.ebay.category_id.trim().length > 0 &&
        state.ebay.picture_urls.length > 0
      )
    }
    return true
  }, [step, selectedPlatforms.length, state, selectedEbayPlatform])

  const handleNext = async () => {
    setUiError(null)
    if (!stepValid) {
      setUiError('Please complete required fields before continuing.')
      return
    }
    if (step === 1) {
      const loaded = await loadDraftIfNeeded()
      if (!loaded) return
    }
    if (step < 3) setStep((prev) => (prev + 1) as WizardStep)
  }

  const handleBack = () => {
    setUiError(null)
    if (step > 0) setStep((prev) => (prev - 1) as WizardStep)
  }

  const handlePublish = async () => {
    setUiError(null)
    if (!selectedEbayPlatform) {
      setUiError('Select at least one eBay destination for this flow.')
      return
    }
    if (!state.variant_id) {
      setUiError('Variant is required.')
      return
    }

    const basePrice = parseNumber(state.base_price)
    const qty = parseNumber(state.global_quantity)
    const override = parseNumber(state.ebay.price_override)
    const price = override ?? basePrice
    if (!price || !qty) {
      setUiError('Price and quantity are required.')
      return
    }

    const payload = {
      platform: selectedEbayPlatform,
      variant_id: state.variant_id,
      title: state.master_title,
      description: state.description,
      category_id: state.ebay.category_id,
      price,
      quantity: qty,
      picture_urls: state.ebay.picture_urls,
      condition_text: state.ebay.condition_text,
      upc: state.ebay.upc || undefined,
      brand: state.ebay.brand || undefined,
      color: state.ebay.color || undefined,
      dimensions: {
        length: parseNumber(state.ebay.length),
        width: parseNumber(state.ebay.width),
        height: parseNumber(state.ebay.height),
        weight: parseNumber(state.ebay.weight),
      },
      extra_specifics: [],
    }

    await publishMutation.mutateAsync(payload)
  }

  const renderDestinationStep = () => (
    <Stack spacing={2}>
      <Typography variant="h6">Step 1: Destination Selection</Typography>
      <Typography variant="body2" color="text.secondary">
        Choose destination platforms. eBay is fully wired in this iteration; other platforms are state-ready.
      </Typography>
      <Grid container spacing={1}>
        {DESTINATION_OPTIONS.map((opt) => (
          <Grid item xs={12} sm={6} key={opt.key}>
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={state.destinations[opt.key]}
                    onChange={(e) => {
                      const checked = e.target.checked
                      setState((prev) => ({
                        ...prev,
                        destinations: {
                          ...prev.destinations,
                          [opt.key]: checked,
                        },
                      }))
                    }}
                  />
                }
                label={opt.label}
              />
            </Paper>
          </Grid>
        ))}
      </Grid>
    </Stack>
  )

  const renderCoreDetailsStep = () => (
    <Stack spacing={2}>
      <Typography variant="h6">Step 2: Core Details</Typography>
      <TextField
        select
        label="Variant *"
        value={state.variant_id ?? ''}
        onChange={(e) => {
          const id = Number(e.target.value)
          const variant = variantsData.find((v) => v.id === id)
          setState((prev) => ({
            ...prev,
            variant_id: id,
            master_sku: variant?.full_sku || prev.master_sku,
          }))
          setDraftLoadedForPlatform(null)
        }}
        disabled={variantsLoading}
      >
        {variantsData.map((v) => (
          <MenuItem key={v.id} value={v.id}>
            {v.full_sku}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label="Master Title *"
        value={state.master_title}
        onChange={(e) => setState((prev) => ({ ...prev, master_title: e.target.value }))}
      />
      <TextField
        label="Master SKU *"
        value={state.master_sku}
        onChange={(e) => setState((prev) => ({ ...prev, master_sku: e.target.value }))}
      />
      <Grid container spacing={2}>
        <Grid item xs={12} sm={6}>
          <TextField
            label="Base Price *"
            type="number"
            value={state.base_price}
            onChange={(e) => setState((prev) => ({ ...prev, base_price: e.target.value }))}
            fullWidth
          />
        </Grid>
        <Grid item xs={12} sm={6}>
          <TextField
            label="Global Quantity *"
            type="number"
            value={state.global_quantity}
            onChange={(e) => setState((prev) => ({ ...prev, global_quantity: e.target.value }))}
            fullWidth
          />
        </Grid>
      </Grid>
      <TextField
        label="Description *"
        multiline
        minRows={4}
        value={state.description}
        onChange={(e) => setState((prev) => ({ ...prev, description: e.target.value }))}
      />
      {draftMutation.isPending ? <Alert severity="info">Loading eBay draft defaults...</Alert> : null}
      {draftLoadedForPlatform ? (
        <Alert severity="success">Draft defaults loaded for {draftLoadedForPlatform}.</Alert>
      ) : null}
    </Stack>
  )

  const renderPlatformSpecificsStep = () => (
    <Stack spacing={2}>
      <Typography variant="h6">Step 3: Platform Specifics</Typography>
      <Tabs
        value={activePlatformTab}
        onChange={(_e, value: DestinationKey) => setActivePlatformTab(value)}
        variant="scrollable"
      >
        {selectedPlatforms.map((platform) => (
          <Tab key={platform} value={platform} label={platform} />
        ))}
      </Tabs>
      <Divider />

      {EBAY_KEYS.includes(activePlatformTab) ? (
        <Stack spacing={2}>
          <TextField
            label="Item Condition *"
            value={state.ebay.condition_text}
            onChange={(e) =>
              setState((prev) => ({
                ...prev,
                ebay: { ...prev.ebay, condition_text: e.target.value },
              }))
            }
          />
          <TextField
            label="Shipping Policy ID"
            value={state.ebay.shipping_policy_id}
            disabled
            helperText="Read from store defaults via draft endpoint"
          />
          <Grid container spacing={2}>
            <Grid item xs={12} sm={3}>
              <TextField
                label="Length"
                type="number"
                value={state.ebay.length}
                onChange={(e) =>
                  setState((prev) => ({ ...prev, ebay: { ...prev.ebay, length: e.target.value } }))
                }
                fullWidth
              />
            </Grid>
            <Grid item xs={12} sm={3}>
              <TextField
                label="Width"
                type="number"
                value={state.ebay.width}
                onChange={(e) =>
                  setState((prev) => ({ ...prev, ebay: { ...prev.ebay, width: e.target.value } }))
                }
                fullWidth
              />
            </Grid>
            <Grid item xs={12} sm={3}>
              <TextField
                label="Height"
                type="number"
                value={state.ebay.height}
                onChange={(e) =>
                  setState((prev) => ({ ...prev, ebay: { ...prev.ebay, height: e.target.value } }))
                }
                fullWidth
              />
            </Grid>
            <Grid item xs={12} sm={3}>
              <TextField
                label="Weight"
                type="number"
                value={state.ebay.weight}
                onChange={(e) =>
                  setState((prev) => ({ ...prev, ebay: { ...prev.ebay, weight: e.target.value } }))
                }
                fullWidth
              />
            </Grid>
          </Grid>
          <TextField
            label="Price Override"
            type="number"
            value={state.ebay.price_override}
            onChange={(e) => setState((prev) => ({ ...prev, ebay: { ...prev.ebay, price_override: e.target.value } }))}
            helperText="If empty, Base Price from step 2 is used"
          />
          <TextField
            select
            label="Primary Category *"
            value={state.ebay.category_id}
            onChange={(e) => setState((prev) => ({ ...prev, ebay: { ...prev.ebay, category_id: e.target.value } }))}
          >
            {state.ebay.suggested_categories.map((s) => (
              <MenuItem key={s.category_id} value={s.category_id}>
                {formatCategoryLabel(s)}
              </MenuItem>
            ))}
          </TextField>
          {categorySuggestionMutation.isPending ? (
            <Alert severity="info">Loading category suggestions...</Alert>
          ) : null}
          <TextField
            label="Picture URLs (comma separated) *"
            value={state.ebay.picture_urls.join(', ')}
            onChange={(e) =>
              setState((prev) => ({
                ...prev,
                ebay: {
                  ...prev.ebay,
                  picture_urls: e.target.value
                    .split(',')
                    .map((x) => x.trim())
                    .filter(Boolean),
                },
              }))
            }
          />
        </Stack>
      ) : (
        <Alert severity="info">{activePlatformTab} overrides are scaffolded in state for a follow-up iteration.</Alert>
      )}
    </Stack>
  )

  const renderReviewStep = () => {
    const effectivePrice = parseNumber(state.ebay.price_override) ?? parseNumber(state.base_price)
    return (
      <Stack spacing={2}>
        <Typography variant="h6">Step 4: Validate & Publish</Typography>
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              Review
            </Typography>
            <Typography variant="body2">Destination: {selectedEbayPlatform || 'N/A'}</Typography>
            <Typography variant="body2">Variant ID: {state.variant_id || 'N/A'}</Typography>
            <Typography variant="body2">Title: {state.master_title}</Typography>
            <Typography variant="body2">SKU: {state.master_sku}</Typography>
            <Typography variant="body2">Price: {effectivePrice ?? 'N/A'}</Typography>
            <Typography variant="body2">Qty: {state.global_quantity}</Typography>
            <Typography variant="body2">Category: {state.ebay.category_id || 'N/A'}</Typography>
            <Typography variant="body2">Condition: {state.ebay.condition_text || 'N/A'}</Typography>
            <Typography variant="body2">Pictures: {state.ebay.picture_urls.length}</Typography>
          </CardContent>
        </Card>

        <Button
          variant="contained"
          onClick={handlePublish}
          disabled={publishMutation.isPending}
        >
          {publishMutation.isPending ? 'Uploading...' : 'Validate & Upload'}
        </Button>
      </Stack>
    )
  }

  const renderStepContent = () => {
    if (step === 0) return renderDestinationStep()
    if (step === 1) return renderCoreDetailsStep()
    if (step === 2) return renderPlatformSpecificsStep()
    return renderReviewStep()
  }

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
        <Typography variant="h4">Create New Listing</Typography>
      </Stack>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Step {step + 1} of {STEPS.length}: {STEPS[step]}
        </Typography>
      </Paper>

      {uiError ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {uiError}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2 }}>{renderStepContent()}</Paper>

      <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
        <Button disabled={step === 0 || publishMutation.isPending} onClick={handleBack}>
          Back
        </Button>
        {step < 3 ? (
          <Button variant="contained" onClick={handleNext} disabled={!stepValid || publishMutation.isPending}>
            Next
          </Button>
        ) : null}
      </Stack>
    </Box>
  )
}
