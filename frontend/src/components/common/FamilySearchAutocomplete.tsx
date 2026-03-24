import { Box, Typography } from '@mui/material'

import { searchFamilyOptions } from '../../api/catalogSearch'
import type { FamilySearchResult } from '../../types/inventory'
import AsyncSearchAutocomplete from './AsyncSearchAutocomplete'

interface FamilySearchAutocompleteProps {
  value: FamilySearchResult | null
  onChange: (value: FamilySearchResult | null) => void
  label?: string
  placeholder?: string
  width?: number | string
  disabled?: boolean
}

export default function FamilySearchAutocomplete({
  value,
  onChange,
  label = 'Select parent product',
  placeholder = 'Type product id or product name...',
  width = '100%',
  disabled = false,
}: FamilySearchAutocompleteProps) {
  return (
    <AsyncSearchAutocomplete<FamilySearchResult>
      value={value}
      onChange={onChange}
      queryKeyPrefix="familySearch"
      searchFn={searchFamilyOptions}
      getOptionLabel={(option) => `${option.product_id} - ${option.base_name}`}
      isOptionEqualToValue={(option, selected) => option.product_id === selected.product_id}
      label={label}
      placeholder={placeholder}
      width={width}
      disabled={disabled}
      renderOption={(props, option) => (
        <li {...props} key={option.product_id}>
          <Box>
            <Typography variant="body2" fontWeight={600}>
              {option.base_name}
            </Typography>
            <Typography variant="caption" color="text.secondary" fontFamily="monospace">
              {option.product_id}
            </Typography>
          </Box>
        </li>
      )}
    />
  )
}
