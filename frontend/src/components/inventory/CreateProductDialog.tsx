import { useState, useMemo } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Box,
  Typography,
  Divider,
  Autocomplete,
  List,
  ListItem,
  ListItemText,
  Chip,
  Grid,
  InputAdornment,
  CircularProgress,
  Paper,
  ToggleButton,
  ToggleButtonGroup,
  Alert,
} from '@mui/material'
import { Add, Search, AddCircle, ContentCopy } from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axiosClient from '../../api/axiosClient'
import { CATALOG, LOOKUPS } from '../../api/endpoints'
import {
  Brand,
  Color,
  Condition,
  LCIDefinition,
  ProductIdentity,
  ProductFamily,
  Variant,
} from '../../types/inventory'

type CreationMode = 'new' | 'existing'

interface CreateProductDialogProps {
  open: boolean
  onClose: () => void
  onCreated?: (fullSku: string) => void
}

type ItemType = 'Product' | 'P' | 'B' | 'K'

const typeOptions: { value: ItemType; label: string; description: string }[] = [
  { value: 'Product', label: 'Product', description: 'A standard sellable product' },
  { value: 'P', label: 'Part', description: 'A component part of a product' },
  { value: 'B', label: 'Bundle', description: 'A collection of products sold together' },
  { value: 'K', label: 'Kit', description: 'A kit with included items' },
]

export default function CreateProductDialog({ open, onClose, onCreated }: CreateProductDialogProps) {
  const queryClient = useQueryClient()
  
  // Creation mode: 'new' = create entirely new product, 'existing' = add variant to existing parent
  const [creationMode, setCreationMode] = useState<CreationMode>('new')
  
  // For 'existing' mode - select an existing parent identity
  const [selectedExistingParent, setSelectedExistingParent] = useState<ProductIdentity | null>(null)
  
  // Form state
  const [itemType, setItemType] = useState<ItemType>('Product')
  const [name, setName] = useState('')
  const [dimensionLength, setDimensionLength] = useState('')
  const [dimensionWidth, setDimensionWidth] = useState('')
  const [dimensionHeight, setDimensionHeight] = useState('')
  const [weight, setWeight] = useState('')
  const [selectedBrand, setSelectedBrand] = useState<Brand | null>(null)
  const [selectedColor, setSelectedColor] = useState<Color | null>(null)
  const [selectedCondition, setSelectedCondition] = useState<Condition | null>(null)
  const [newBrandName, setNewBrandName] = useState('')
  const [newColorName, setNewColorName] = useState('')
  const [newColorCode, setNewColorCode] = useState('')
  const [newConditionName, setNewConditionName] = useState('')
  const [newConditionCode, setNewConditionCode] = useState('')
  
  // Bundle-specific
  const [bundleComponents, setBundleComponents] = useState<ProductIdentity[]>([])
  const [componentSearchQuery, setComponentSearchQuery] = useState('')
  
  // Kit-specific
  const [kitIncludedProducts, setKitIncludedProducts] = useState('')
  
  // Part-specific
  const [selectedParentProduct, setSelectedParentProduct] = useState<ProductIdentity | null>(null)
  const [selectedLCI, setSelectedLCI] = useState<LCIDefinition | null>(null)
  const [newLCIComponentName, setNewLCIComponentName] = useState('')

  // Fetch lookups
  const { data: brandsData } = useQuery({
    queryKey: ['brands'],
    queryFn: async () => {
      const response = await axiosClient.get(LOOKUPS.BRANDS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: colorsData } = useQuery({
    queryKey: ['colors'],
    queryFn: async () => {
      const response = await axiosClient.get(LOOKUPS.COLORS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: conditionsData } = useQuery({
    queryKey: ['conditions'],
    queryFn: async () => {
      const response = await axiosClient.get(LOOKUPS.CONDITIONS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: identitiesData } = useQuery({
    queryKey: ['identities'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.IDENTITIES, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  // Fetch families for enriching identity data
  const { data: familiesData } = useQuery({
    queryKey: ['families'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.FAMILIES, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  // Fetch existing variants (to know what color/condition combos exist)
  const { data: variantsData } = useQuery({
    queryKey: ['variants'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.VARIANTS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  // Enhanced identities with family data
  const enhancedIdentities = useMemo(() => {
    if (!identitiesData || !familiesData) return []
    const familyMap = new Map<number, ProductFamily>()
    familiesData.forEach((f: ProductFamily) => familyMap.set(f.product_id, f))
    return identitiesData.map((i: ProductIdentity) => ({
      ...i,
      family: familyMap.get(i.product_id),
    }))
  }, [identitiesData, familiesData])

  // Fetch LCI definitions for selected parent product
  const { data: lciData } = useQuery({
    queryKey: ['lci-definitions', selectedParentProduct?.product_id],
    queryFn: async () => {
      if (!selectedParentProduct) return []
      const response = await axiosClient.get(LOOKUPS.LCI_DEFINITIONS, {
        params: { product_id: selectedParentProduct.product_id, limit: 100 }
      })
      return response.data.items || []
    },
    enabled: open && itemType === 'P' && !!selectedParentProduct,
  })

  // Mutations
  const createBrandMutation = useMutation({
    mutationFn: async (name: string) => {
      const response = await axiosClient.post(LOOKUPS.BRANDS, { name })
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['brands'] })
      setSelectedBrand(data)
      setNewBrandName('')
    },
  })

  const createColorMutation = useMutation({
    mutationFn: async ({ name, code }: { name: string; code: string }) => {
      const response = await axiosClient.post(LOOKUPS.COLORS, { name, code })
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['colors'] })
      setSelectedColor(data)
      setNewColorName('')
      setNewColorCode('')
    },
  })

  const createConditionMutation = useMutation({
    mutationFn: async ({ name, code }: { name: string; code: string }) => {
      const response = await axiosClient.post(LOOKUPS.CONDITIONS, { name, code })
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['conditions'] })
      setSelectedCondition(data)
      setNewConditionName('')
      setNewConditionCode('')
    },
  })

  const createLCIMutation = useMutation({
    mutationFn: async ({ product_id, component_name }: { product_id: number; component_name: string }) => {
      const response = await axiosClient.post(LOOKUPS.LCI_DEFINITIONS, { product_id, component_name })
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['lci-definitions', selectedParentProduct?.product_id] })
      setSelectedLCI(data)
      setNewLCIComponentName('')
    },
  })

  // Mutation for adding variant to existing product
  const createVariantMutation = useMutation({
    mutationFn: async (data: { identity_id: number; color_code?: string; condition_code?: string; product_id?: number; newName?: string }) => {
      // If a new name is provided and different, update the family first
      if (data.newName && data.product_id) {
        await axiosClient.put(CATALOG.FAMILY(data.product_id), {
          base_name: data.newName,
        })
      }
      
      // Only include color_code and condition_code if they have values
      const payload: { identity_id: number; color_code?: string; condition_code?: string } = {
        identity_id: data.identity_id,
      }
      if (data.color_code) payload.color_code = data.color_code
      if (data.condition_code) payload.condition_code = data.condition_code
      
      const response = await axiosClient.post(CATALOG.VARIANTS, payload)
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['variants'] })
      queryClient.invalidateQueries({ queryKey: ['families'] })
      queryClient.invalidateQueries({ queryKey: ['identities'] })
      handleClose()
      if (data?.full_sku) onCreated?.(data.full_sku)
    },
    onError: (error: any) => {
      console.error('Failed to create variant:', error)
      alert(error.response?.data?.detail || 'Failed to create variant')
    },
  })

  const createProductMutation = useMutation({
    mutationFn: async (data: any) => {
      let productId: number
      
      // For Parts, use the parent product's product_id (don't create a new family)
      if (data.type === 'P' && data.parent_product_id) {
        productId = data.parent_product_id
      } else {
        // For other types, create a new family
        const familyResponse = await axiosClient.post(CATALOG.FAMILIES, {
          base_name: data.name,
          brand_id: data.brand_id,
          dimension_length: data.dimension_length,
          dimension_width: data.dimension_width,
          dimension_height: data.dimension_height,
          weight: data.weight,
          kit_included_products: data.kit_included_products,
        })
        productId = familyResponse.data.product_id
      }
      
      // Then create the identity
      const identityResponse = await axiosClient.post(CATALOG.IDENTITIES, {
        product_id: productId,
        type: data.type,
        lci: data.lci,
      })
      
      // Always create a variant (even without color/condition for display purposes)
      const variantPayload: { identity_id: number; color_code?: string; condition_code?: string } = {
        identity_id: identityResponse.data.id,
      }
      if (data.color_code) variantPayload.color_code = data.color_code
      if (data.condition_code) variantPayload.condition_code = data.condition_code
      
      const variantResponse = await axiosClient.post(CATALOG.VARIANTS, variantPayload)
      
      // If bundle, add components
      if (data.type === 'B' && data.component_ids?.length > 0) {
        for (const componentId of data.component_ids) {
          await axiosClient.post(CATALOG.BUNDLES, {
            parent_identity_id: identityResponse.data.id,
            child_identity_id: componentId,
            quantity_required: 1,
            role: 'Primary',
          })
        }
      }
      
      return variantResponse.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['variants'] })
      queryClient.invalidateQueries({ queryKey: ['identities'] })
      queryClient.invalidateQueries({ queryKey: ['families'] })
      handleClose()
      if (data?.full_sku) onCreated?.(data.full_sku)
    },
    onError: (error: any) => {
      console.error('Failed to create product:', error)
      alert(error.response?.data?.detail || 'Failed to create product')
    },
  })

  const handleClose = () => {
    // Reset form
    setCreationMode('new')
    setSelectedExistingParent(null)
    setItemType('Product')
    setName('')
    setDimensionLength('')
    setDimensionWidth('')
    setDimensionHeight('')
    setWeight('')
    setSelectedBrand(null)
    setSelectedColor(null)
    setSelectedCondition(null)
    setBundleComponents([])
    setKitIncludedProducts('')
    setSelectedParentProduct(null)
    setSelectedLCI(null)
    onClose()
  }

  const handleSubmit = () => {
    // Handle 'existing' mode - just create a new variant for the existing identity
    if (creationMode === 'existing' && selectedExistingParent) {
      // Check if name was changed
      const originalName = selectedExistingParent.family?.base_name || ''
      const nameChanged = name !== originalName && name.trim() !== ''
      
      createVariantMutation.mutate({
        identity_id: selectedExistingParent.id,
        color_code: selectedColor?.code,
        condition_code: selectedCondition?.code,
        product_id: nameChanged ? selectedExistingParent.product_id : undefined,
        newName: nameChanged ? name : undefined,
      })
      return
    }

    // Handle 'new' mode - create family, identity, and variant
    const data: any = {
      type: itemType,
      name,
      brand_id: selectedBrand?.id,
      dimension_length: dimensionLength ? parseFloat(dimensionLength) : undefined,
      dimension_width: dimensionWidth ? parseFloat(dimensionWidth) : undefined,
      dimension_height: dimensionHeight ? parseFloat(dimensionHeight) : undefined,
      weight: weight ? parseFloat(weight) : undefined,
    }
    
    // Type-specific fields
    if (itemType !== 'B') {
      data.color_code = selectedColor?.code
      data.condition_code = selectedCondition?.code
    }
    
    if (itemType === 'B') {
      data.component_ids = bundleComponents.map((c) => c.id)
    }
    
    if (itemType === 'K') {
      data.kit_included_products = kitIncludedProducts
    }
    
    if (itemType === 'P' && selectedParentProduct) {
      data.lci = selectedLCI?.lci_index
      // Pass the parent's product_id so we attach to existing family
      data.parent_product_id = selectedParentProduct.product_id
    }
    
    createProductMutation.mutate(data)
  }

  const handleAddBrand = () => {
    if (newBrandName.trim()) {
      createBrandMutation.mutate(newBrandName.trim())
    }
  }

  const handleAddColor = () => {
    if (newColorName.trim() && newColorCode.trim()) {
      createColorMutation.mutate({
        name: newColorName.trim(),
        code: newColorCode.trim().toUpperCase(),
      })
    }
  }

  const handleAddCondition = () => {
    if (newConditionName.trim() && newConditionCode.trim()) {
      createConditionMutation.mutate({
        name: newConditionName.trim(),
        code: newConditionCode.trim().toUpperCase(),
      })
    }
  }

  const handleAddLCI = () => {
    if (selectedParentProduct && newLCIComponentName.trim()) {
      createLCIMutation.mutate({
        product_id: selectedParentProduct.product_id,
        component_name: newLCIComponentName.trim(),
      })
    }
  }

  const handleAddBundleComponent = (identity: ProductIdentity) => {
    if (!bundleComponents.find((c) => c.id === identity.id)) {
      setBundleComponents([...bundleComponents, identity])
    }
    setComponentSearchQuery('')
  }

  const handleRemoveBundleComponent = (id: number) => {
    setBundleComponents(bundleComponents.filter((c) => c.id !== id))
  }

  // Filter identities for component search
  const filteredIdentities = (identitiesData || []).filter((identity: ProductIdentity) => {
    if (!componentSearchQuery.trim()) return false
    const query = componentSearchQuery.toLowerCase()
    return identity.generated_upis_h?.toLowerCase().includes(query)
  })

  // Filter parent products (only Products, not Parts or Bundles) - use enhanced identities with family data
  const parentProductOptions = enhancedIdentities.filter(
    (identity: ProductIdentity & { family?: ProductFamily }) => identity.type === 'Product'
  )

  // Handle selecting an existing parent - auto-fill relevant data
  const handleSelectExistingParent = (parent: (ProductIdentity & { family?: ProductFamily }) | null) => {
    setSelectedExistingParent(parent)
    if (parent && parent.family) {
      // Auto-fill form fields from existing parent
      setName(parent.family.base_name || '')
      setDimensionLength(parent.family.dimension_length?.toString() || '')
      setDimensionWidth(parent.family.dimension_width?.toString() || '')
      setDimensionHeight(parent.family.dimension_height?.toString() || '')
      setWeight(parent.family.weight?.toString() || '')
      setItemType(parent.type as ItemType)
      // Find and set the brand
      if (parent.family.brand_id && brandsData) {
        const brand = brandsData.find((b: Brand) => b.id === parent.family?.brand_id)
        setSelectedBrand(brand || null)
      }
    }
  }

  // Generate SKU preview based on current form inputs
  const skuPreview = useMemo(() => {
    if (creationMode === 'existing' && selectedExistingParent) {
      // For existing parent, use its UPIS-H as base
      const parts: string[] = [selectedExistingParent.generated_upis_h || '?????']
      if (selectedColor?.code) parts.push(selectedColor.code)
      if (selectedCondition?.code) parts.push(selectedCondition.code)
      return parts.join('-')
    } else {
      // For new product, show placeholder format
      const typeCode = itemType === 'Product' ? 'P' : itemType
      
      // For Parts, use the parent product's ID if selected
      if (itemType === 'P' && selectedParentProduct) {
        const parentId = selectedParentProduct.product_id.toString().padStart(5, '0')
        const parts: string[] = [parentId, 'P']
        if (selectedLCI) {
          parts.push(selectedLCI.lci_index.toString().padStart(2, '0'))
        }
        if (selectedColor?.code) parts.push(selectedColor.code)
        if (selectedCondition?.code) parts.push(selectedCondition.code)
        return parts.join('-')
      }
      
      // For other types, show placeholder
      const parts: string[] = ['XXXXX'] // Product ID will be generated
      parts.push(typeCode)
      if (selectedColor?.code) parts.push(selectedColor.code)
      if (selectedCondition?.code) parts.push(selectedCondition.code)
      return parts.join('-')
    }
  }, [creationMode, selectedExistingParent, itemType, selectedColor, selectedCondition, selectedLCI, selectedParentProduct])

  // Get existing variants for the selected parent (to show what already exists)
  const existingVariantsForParent = useMemo(() => {
    if (!selectedExistingParent || !variantsData) return []
    return (variantsData as Variant[]).filter(
      (v) => v.identity_id === selectedExistingParent.id
    )
  }, [selectedExistingParent, variantsData])

  const isValid = (
    creationMode === 'existing' 
      ? selectedExistingParent !== null
      : name.trim().length > 0
  ) && (
    itemType !== 'B' || bundleComponents.length > 0
  ) && (
    itemType !== 'P' || (selectedParentProduct && selectedLCI)
  )

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>Add New Item</DialogTitle>
      <DialogContent>
        <Box sx={{ mt: 2 }}>
          {/* Creation Mode Toggle */}
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              What would you like to create?
            </Typography>
            <ToggleButtonGroup
              value={creationMode}
              exclusive
              onChange={(_, value) => value && setCreationMode(value)}
              fullWidth
            >
              <ToggleButton value="new">
                <AddCircle sx={{ mr: 1 }} />
                New Product
              </ToggleButton>
              <ToggleButton value="existing">
                <ContentCopy sx={{ mr: 1 }} />
                Variant for Existing Product
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>

          <Divider sx={{ mb: 3 }} />

          {/* Existing Parent Selection (only in 'existing' mode) */}
          {creationMode === 'existing' && (
            <Box sx={{ mb: 3 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Select Existing Parent Product *
              </Typography>
              <Autocomplete
                options={enhancedIdentities.filter((i: any) => i.type === 'Product' || i.type === 'K')}
                getOptionLabel={(option: any) =>
                  `${option.generated_upis_h} - ${option.family?.base_name || 'Unknown'}`
                }
                value={selectedExistingParent}
                onChange={(_, value) => handleSelectExistingParent(value)}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    placeholder="Search by UPIS-H or product name..."
                    InputProps={{
                      ...params.InputProps,
                      startAdornment: (
                        <InputAdornment position="start">
                          <Search />
                        </InputAdornment>
                      ),
                    }}
                  />
                )}
                renderOption={(props, option: any) => (
                  <li {...props} key={option.id}>
                    <Box>
                      <Typography variant="body2" fontFamily="monospace">
                        {option.generated_upis_h}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {option.family?.base_name || 'Unknown'}
                        {option.family?.brand?.name && ` • ${option.family.brand.name}`}
                      </Typography>
                    </Box>
                  </li>
                )}
              />
              {selectedExistingParent && existingVariantsForParent.length > 0 && (
                <Alert severity="info" sx={{ mt: 2 }}>
                  <Typography variant="body2">
                    Existing variants for this product:
                  </Typography>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 1 }}>
                    {existingVariantsForParent.map((v: Variant) => (
                      <Chip
                        key={v.id}
                        size="small"
                        label={`${v.color_code || '-'}/${v.condition_code || '-'}`}
                        variant="outlined"
                      />
                    ))}
                  </Box>
                </Alert>
              )}

              {/* Variant Name - editable for customization */}
              {selectedExistingParent && (
                <Box sx={{ mt: 2 }}>
                  <TextField
                    fullWidth
                    label="Variant Name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Customize the name for this variant..."
                    helperText="Leave as-is or edit to update the product name"
                  />
                </Box>
              )}

              <Divider sx={{ mt: 3, mb: 3 }} />
            </Box>
          )}

          {/* Type Selection - only for new products */}
          {creationMode === 'new' && (
            <FormControl fullWidth sx={{ mb: 3 }}>
              <InputLabel>Type *</InputLabel>
              <Select
                value={itemType}
                label="Type *"
                onChange={(e) => setItemType(e.target.value as ItemType)}
              >
                {typeOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    <Box>
                      <Typography variant="body1">{option.label}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {option.description}
                      </Typography>
                    </Box>
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}

          {creationMode === 'new' && <Divider sx={{ mb: 3 }} />}

          {/* Common Fields - Only show for new products or when editing */}
          {creationMode === 'new' && (
            <>
              <Typography variant="subtitle2" sx={{ mb: 2 }}>
                Basic Information
              </Typography>
              
              <TextField
                fullWidth
            label="Name *"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Enter product name (e.g., 'Bose 201 Series IV Speaker')"
            sx={{ mb: 2 }}
          />

          {/* Brand Selection */}
          <Box sx={{ mb: 2 }}>
            <Autocomplete
              options={brandsData || []}
              getOptionLabel={(option: Brand) => option.name}
              value={selectedBrand}
              onChange={(_, value) => setSelectedBrand(value)}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Brand / Manufacturer"
                  placeholder="Search or add a brand..."
                />
              )}
              renderOption={(props, option) => (
                <li {...props} key={option.id}>
                  {option.name}
                </li>
              )}
            />
            <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
              <TextField
                size="small"
                placeholder="New brand name"
                value={newBrandName}
                onChange={(e) => setNewBrandName(e.target.value)}
                sx={{ flexGrow: 1 }}
              />
              <Button
                size="small"
                variant="outlined"
                startIcon={<Add />}
                onClick={handleAddBrand}
                disabled={!newBrandName.trim() || createBrandMutation.isPending}
              >
                Add
              </Button>
            </Box>
          </Box>

          {/* Dimensions */}
          <Typography variant="subtitle2" sx={{ mb: 2, mt: 3 }}>
            Dimensions & Weight
          </Typography>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={4}>
              <TextField
                fullWidth
                label="Length"
                type="number"
                value={dimensionLength}
                onChange={(e) => setDimensionLength(e.target.value)}
                InputProps={{
                  endAdornment: <InputAdornment position="end">in</InputAdornment>,
                }}
                placeholder="0.00"
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                fullWidth
                label="Width"
                type="number"
                value={dimensionWidth}
                onChange={(e) => setDimensionWidth(e.target.value)}
                InputProps={{
                  endAdornment: <InputAdornment position="end">in</InputAdornment>,
                }}
                placeholder="0.00"
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                fullWidth
                label="Height"
                type="number"
                value={dimensionHeight}
                onChange={(e) => setDimensionHeight(e.target.value)}
                InputProps={{
                  endAdornment: <InputAdornment position="end">in</InputAdornment>,
                }}
                placeholder="0.00"
              />
            </Grid>
          </Grid>
          <TextField
            fullWidth
            label="Weight"
            type="number"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
            InputProps={{
              endAdornment: <InputAdornment position="end">lb</InputAdornment>,
            }}
            placeholder="0.00"
            sx={{ mb: 3 }}
          />

          <Divider sx={{ mb: 3 }} />
            </>
          )}

          {/* Color & Condition - Not for Bundles, shown in both new and existing modes */}
          {(creationMode === 'new' ? itemType !== 'B' : true) && (
            <>
              <Typography variant="subtitle2" sx={{ mb: 2 }}>
                Variant Options
              </Typography>
              
              {/* Color */}
              <Box sx={{ mb: 2 }}>
                <Autocomplete
                  options={colorsData || []}
                  getOptionLabel={(option: Color) => `${option.name} - ${option.code}`}
                  value={selectedColor}
                  onChange={(_, value) => setSelectedColor(value)}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label="Color"
                      placeholder="Select or add a color..."
                    />
                  )}
                  renderOption={(props, option) => (
                    <li {...props} key={option.id}>
                      {option.name} - {option.code}
                    </li>
                  )}
                />
                <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
                  <TextField
                    size="small"
                    placeholder="Color name"
                    value={newColorName}
                    onChange={(e) => setNewColorName(e.target.value)}
                    sx={{ flexGrow: 1 }}
                  />
                  <TextField
                    size="small"
                    placeholder="Code (2 chars)"
                    value={newColorCode}
                    onChange={(e) => setNewColorCode(e.target.value.slice(0, 2))}
                    sx={{ width: 100 }}
                  />
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<Add />}
                    onClick={handleAddColor}
                    disabled={!newColorName.trim() || !newColorCode.trim() || createColorMutation.isPending}
                  >
                    Add
                  </Button>
                </Box>
              </Box>

              {/* Condition */}
              <Box sx={{ mb: 3 }}>
                <Autocomplete
                  options={conditionsData || []}
                  getOptionLabel={(option: Condition) => `${option.name} - ${option.code}`}
                  value={selectedCondition}
                  onChange={(_, value) => setSelectedCondition(value)}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label="Condition"
                      placeholder="Select or add a condition..."
                    />
                  )}
                  renderOption={(props, option) => (
                    <li {...props} key={option.id}>
                      {option.name} - {option.code}
                    </li>
                  )}
                />
                <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
                  <TextField
                    size="small"
                    placeholder="Condition name"
                    value={newConditionName}
                    onChange={(e) => setNewConditionName(e.target.value)}
                    sx={{ flexGrow: 1 }}
                  />
                  <TextField
                    size="small"
                    placeholder="Code (1 char)"
                    value={newConditionCode}
                    onChange={(e) => setNewConditionCode(e.target.value.slice(0, 1))}
                    sx={{ width: 100 }}
                  />
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<Add />}
                    onClick={handleAddCondition}
                    disabled={!newConditionName.trim() || !newConditionCode.trim() || createConditionMutation.isPending}
                  >
                    Add
                  </Button>
                </Box>
              </Box>

              <Divider sx={{ mb: 3 }} />
            </>
          )}

          {/* Bundle-specific: Component SKUs - only for new products */}
          {creationMode === 'new' && itemType === 'B' && (
            <>
              <Typography variant="subtitle2" sx={{ mb: 2 }}>
                Bundle Components *
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Search and add existing products to include in this bundle. Components must already exist in the system.
              </Typography>
              
              <TextField
                fullWidth
                label="Search Components by UPIS-H"
                value={componentSearchQuery}
                onChange={(e) => setComponentSearchQuery(e.target.value)}
                placeholder="Type to search (e.g., '00845')"
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Search />
                    </InputAdornment>
                  ),
                }}
                sx={{ mb: 1 }}
              />
              
              {filteredIdentities.length > 0 && (
                <Paper variant="outlined" sx={{ mb: 2, maxHeight: 200, overflow: 'auto' }}>
                  <List dense>
                    {filteredIdentities.slice(0, 10).map((identity: ProductIdentity) => (
                      <ListItem
                        key={identity.id}
                        button
                        onClick={() => handleAddBundleComponent(identity)}
                        disabled={bundleComponents.some((c) => c.id === identity.id)}
                      >
                        <ListItemText
                          primary={identity.generated_upis_h}
                          secondary={`Type: ${identity.type}`}
                        />
                      </ListItem>
                    ))}
                  </List>
                </Paper>
              )}
              
              {bundleComponents.length > 0 && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="caption" color="text.secondary">
                    Selected Components:
                  </Typography>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
                    {bundleComponents.map((component) => (
                      <Chip
                        key={component.id}
                        label={component.generated_upis_h}
                        onDelete={() => handleRemoveBundleComponent(component.id)}
                      />
                    ))}
                  </Box>
                </Box>
              )}
              
              <Divider sx={{ mb: 3 }} />
            </>
          )}

          {/* Kit-specific: Included Products - only for new products */}
          {creationMode === 'new' && itemType === 'K' && (
            <>
              <Typography variant="subtitle2" sx={{ mb: 2 }}>
                Included Products
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                List the products included in this kit (free-form text).
              </Typography>
              <TextField
                fullWidth
                multiline
                rows={3}
                label="Included Products"
                value={kitIncludedProducts}
                onChange={(e) => setKitIncludedProducts(e.target.value)}
                placeholder="e.g., Speaker unit, Remote control, Power cable, User manual"
                sx={{ mb: 3 }}
              />
              <Divider sx={{ mb: 3 }} />
            </>
          )}

          {/* Part-specific: Parent SKU and LCI - only for new products */}
          {creationMode === 'new' && itemType === 'P' && (
            <>
              <Typography variant="subtitle2" sx={{ mb: 2 }}>
                Part Configuration *
              </Typography>
              
              {/* Parent Product */}
              <Autocomplete
                options={parentProductOptions}
                getOptionLabel={(option: ProductIdentity & { family?: ProductFamily }) => 
                  `${option.generated_upis_h} - ${option.family?.base_name || 'Unknown'}`
                }
                value={selectedParentProduct}
                onChange={(_, value) => {
                  setSelectedParentProduct(value)
                  setSelectedLCI(null)
                }}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label="Parent Product *"
                    placeholder="Search by UPIS-H or product name..."
                  />
                )}
                renderOption={(props, option: ProductIdentity & { family?: ProductFamily }) => (
                  <li {...props} key={option.id}>
                    <Box>
                      <Typography variant="body2" fontFamily="monospace">
                        {option.generated_upis_h}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {option.family?.base_name || 'Unknown'}
                        {option.family?.brand?.name && ` • ${option.family.brand.name}`}
                      </Typography>
                    </Box>
                  </li>
                )}
                sx={{ mb: 2 }}
              />
              
              {selectedParentProduct && (
                <>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    Parent: {(selectedParentProduct as any).family?.base_name || selectedParentProduct.product_id}
                  </Typography>
                  
                  {/* LCI Selection */}
                  <Box sx={{ mb: 2 }}>
                    <Autocomplete
                      options={lciData || []}
                      getOptionLabel={(option: LCIDefinition) => 
                        `${option.lci_index} - ${option.component_name}`
                      }
                      value={selectedLCI}
                      onChange={(_, value) => setSelectedLCI(value)}
                      renderInput={(params) => (
                        <TextField
                          {...params}
                          label="Local Component Index (LCI) *"
                          placeholder="Select or add a component index..."
                        />
                      )}
                      renderOption={(props, option) => (
                        <li {...props} key={option.id}>
                          {option.lci_index} - {option.component_name}
                        </li>
                      )}
                    />
                    <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
                      <TextField
                        size="small"
                        placeholder="Component name (e.g., Motherboard)"
                        value={newLCIComponentName}
                        onChange={(e) => setNewLCIComponentName(e.target.value)}
                        sx={{ flexGrow: 1 }}
                      />
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={<Add />}
                        onClick={handleAddLCI}
                        disabled={!newLCIComponentName.trim() || createLCIMutation.isPending}
                      >
                        Add LCI
                      </Button>
                    </Box>
                    <Typography variant="caption" color="text.secondary">
                      LCI index will be auto-generated
                    </Typography>
                  </Box>
                </>
              )}
              
              <Divider sx={{ mb: 3 }} />
            </>
          )}

          {/* SKU Preview - Always shown */}
          <Paper elevation={0} sx={{ bgcolor: 'primary.50', p: 2, borderRadius: 1, border: '1px solid', borderColor: 'primary.200' }}>
            <Typography variant="subtitle2" sx={{ mb: 1, color: 'primary.main' }}>
              SKU Preview
            </Typography>
            <Typography variant="h6" fontFamily="monospace" sx={{ mb: 1 }}>
              {skuPreview}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {creationMode === 'existing' 
                ? 'Based on selected parent product. Choose color/condition to complete the variant SKU.'
                : 'SKU will be auto-generated when product is created. The XXXXX will be replaced with the actual product ID.'
              }
            </Typography>
          </Paper>

          <Alert severity="info" sx={{ mt: 2 }}>
            Images are uploaded after the SKU is created. Click <strong>Manage Images</strong> from the inventory row,
            or create the item and the image manager will open automatically.
          </Alert>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={!isValid || createProductMutation.isPending || createVariantMutation.isPending}
        >
          {(createProductMutation.isPending || createVariantMutation.isPending) ? (
            <CircularProgress size={24} />
          ) : creationMode === 'existing' ? (
            'Add Variant'
          ) : (
            'Create'
          )}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
