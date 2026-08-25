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
  width?: number | string
  disabled?: boolean
  isDarkMode?: boolean
  includeIdentityTypes?: Array<'Product' | 'P' | 'B' | 'K'>
  excludeIdentityTypes?: Array<'Product' | 'P' | 'B' | 'K'>
}

export default function VariantSearchAutocomplete({
  value,
  onChange,
  label = 'Search variant by name or SKU',
  placeholder = 'Type to search...',
  width = 360,
  disabled = false,
  isDarkMode = true,
  includeIdentityTypes,
  excludeIdentityTypes,
}: VariantSearchAutocompleteProps) {
  const [inputValue, setInputValue] = useState('')
  const debouncedInput = useDebouncedValue(inputValue, 200)
  const getDisplayName = (option: VariantSearchResult) => option.variant_name || option.product_name

  const { data: options = [], isFetching } = useQuery<VariantSearchResult[]>({
    queryKey: [
      'variantSearch',
      debouncedInput,
      (includeIdentityTypes || []).join(','),
      (excludeIdentityTypes || []).join(','),
    ],
    queryFn: () =>
      searchVariants(debouncedInput, 20, {
        includeIdentityTypes,
        excludeIdentityTypes,
      }),
    enabled: debouncedInput.length >= 1,
    staleTime: 30_000,
  })

  return (
    <Autocomplete<VariantSearchResult>
      size="small"
      sx={{
        width,
        '& .MuiInputBase-root': {
          bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.08)' : '#ffffff',
          color: isDarkMode ? '#f8fafc' : '#0f172a',
          borderRadius: 2,
          border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.15)' : '1px solid #cbd5e1',
          '& input': {
            color: isDarkMode ? '#f8fafc !important' : '#0f172a !important',
            WebkitTextFillColor: isDarkMode ? '#f8fafc !important' : '#0f172a !important',
            fontWeight: 600,
            fontSize: 13,
          },
        },
        '& .MuiInputLabel-root': {
          color: isDarkMode ? '#94a3b8' : '#64748b',
          '&.Mui-focused': {
            color: isDarkMode ? '#38bdf8' : '#0284c7',
          },
        },
        '& .MuiSvgIcon-root': {
          color: isDarkMode ? '#94a3b8' : '#64748b',
        },
      }}
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
      slotProps={{
        paper: {
          sx: {
            bgcolor: isDarkMode ? '#0f172a' : '#ffffff',
            color: isDarkMode ? '#f8fafc' : '#0f172a',
            border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.15)' : '1px solid #cbd5e1',
            borderRadius: 2,
            boxShadow: '0 12px 36px rgba(0,0,0,0.5)',
          },
        },
      }}
      renderOption={(props, option) => (
        <li {...props} key={option.id}>
          <Box sx={{ py: 0.5 }}>
            <Typography variant="body2" sx={{ fontWeight: 700, color: isDarkMode ? '#38bdf8' : '#0284c7' }}>
              {option.full_sku}
            </Typography>
            <Typography variant="caption" sx={{ color: isDarkMode ? '#cbd5e1' : '#334155', display: 'block' }}>
              {getDisplayName(option)}
              {option.color_code && ` · ${option.color_code}`}
              {option.condition_code && ` · ${option.condition_code}`}
            </Typography>
            {option.generated_upis_h && (
              <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', display: 'block', fontFamily: 'monospace', fontSize: 10 }}>
                {option.generated_upis_h}
              </Typography>
            )}
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
      noOptionsText={inputValue.length < 1 ? 'Type SKU or Name to search...' : 'No variants found'}
    />
  )
}