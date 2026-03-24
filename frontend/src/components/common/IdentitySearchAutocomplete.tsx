import { Box, Typography } from '@mui/material'

import { searchIdentityOptions } from '../../api/catalogSearch'
import type { IdentitySearchResult, ProductType } from '../../types/inventory'
import AsyncSearchAutocomplete from './AsyncSearchAutocomplete'

interface IdentitySearchAutocompleteProps {
  value: IdentitySearchResult | null
  onChange: (value: IdentitySearchResult | null) => void
  label?: string
  placeholder?: string
  width?: number | string
  disabled?: boolean
  includeTypes?: ProductType[]
  excludeTypes?: ProductType[]
}

export default function IdentitySearchAutocomplete({
  value,
  onChange,
  label = 'Search identity',
  placeholder = 'Type to search by UPIS-H or name...',
  width = 360,
  disabled = false,
  includeTypes,
  excludeTypes,
}: IdentitySearchAutocompleteProps) {
  return (
    <AsyncSearchAutocomplete<IdentitySearchResult>
      value={value}
      onChange={onChange}
      queryKeyPrefix={`identitySearch:${(includeTypes || []).join(',')}:${(excludeTypes || []).join(',')}`}
      searchFn={(query) => searchIdentityOptions(query, { includeTypes, excludeTypes })}
      getOptionLabel={(option) => `${option.generated_upis_h} - ${option.family_name}`}
      isOptionEqualToValue={(option, selected) => option.id === selected.id}
      label={label}
      placeholder={placeholder}
      width={width}
      disabled={disabled}
      renderOption={(props, option) => (
        <li {...props} key={option.id}>
          <Box>
            <Typography variant="body2" fontWeight={600} fontFamily="monospace">
              {option.generated_upis_h}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {option.family_name}
              {option.identity_name ? ` · ${option.identity_name}` : ''}
              {` · ${option.type}`}
            </Typography>
          </Box>
        </li>
      )}
    />
  )
}
