import { useState } from 'react'
import { Autocomplete, Box, TextField, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'

import { searchVariants } from '../../api/orders'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import type { VariantSearchResult } from '../../types/orders'

interface VariantSearchAutocompleteProps {
  value: VariantSearchResult | null
  onChange: (value: VariantSearchResult | null) => void
  label?: string
  placeholder?: string
  width?: number
  disabled?: boolean
}

export default function VariantSearchAutocomplete({
  value,
  onChange,
  label = 'Search variant by name or SKU',
  placeholder = 'Type to search...',
  width = 360,
  disabled = false,
}: VariantSearchAutocompleteProps) {
  const [inputValue, setInputValue] = useState('')
  const debouncedInput = useDebouncedValue(inputValue, 200)
  const getDisplayName = (option: VariantSearchResult) => option.variant_name || option.product_name

  const { data: options = [], isFetching } = useQuery<VariantSearchResult[]>({
    queryKey: ['variantSearch', debouncedInput],
    queryFn: () => searchVariants(debouncedInput),
    enabled: debouncedInput.length >= 1,
    staleTime: 30_000,
  })

  return (
    <Autocomplete<VariantSearchResult>
      size="small"
      sx={{ width }}
      options={options}
      loading={isFetching}
      value={value}
      inputValue={inputValue}
      onChange={(_event, next) => onChange(next)}
      onInputChange={(_event, nextInput) => setInputValue(nextInput)}
      getOptionLabel={(option) => `${option.full_sku} - ${getDisplayName(option)}`}
      isOptionEqualToValue={(option, selected) => option.id === selected.id}
      filterOptions={(x) => x}
      disabled={disabled}
      renderOption={(props, option) => (
        <li {...props} key={option.id}>
          <Box>
            <Typography variant="body2" fontWeight={600}>
              {option.full_sku}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {getDisplayName(option)}
              {option.color_code && ` · ${option.color_code}`}
              {option.condition_code && ` · ${option.condition_code}`}
            </Typography>
          </Box>
        </li>
      )}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={placeholder}
        />
      )}
      noOptionsText={inputValue.length < 1 ? 'Type to search...' : 'No variants found'}
    />
  )
}