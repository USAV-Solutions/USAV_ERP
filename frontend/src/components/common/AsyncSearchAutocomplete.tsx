import { useState, type ReactNode } from 'react'
import { Autocomplete, TextField } from '@mui/material'
import { useQuery } from '@tanstack/react-query'

import { useDebouncedValue } from '../../hooks/useDebouncedValue'

interface AsyncSearchAutocompleteProps<T> {
  value: T | null
  onChange: (value: T | null) => void
  queryKeyPrefix: string
  searchFn: (query: string) => Promise<T[]>
  getOptionLabel: (option: T) => string
  isOptionEqualToValue?: (option: T, selected: T) => boolean
  renderOption?: (props: React.HTMLAttributes<HTMLLIElement>, option: T) => ReactNode
  label?: string
  placeholder?: string
  width?: number | string
  disabled?: boolean
  minChars?: number
  noOptionsText?: string
}

export default function AsyncSearchAutocomplete<T>({
  value,
  onChange,
  queryKeyPrefix,
  searchFn,
  getOptionLabel,
  isOptionEqualToValue,
  renderOption,
  label,
  placeholder = 'Type to search...',
  width = 360,
  disabled = false,
  minChars = 1,
  noOptionsText = 'No results found',
}: AsyncSearchAutocompleteProps<T>) {
  const [inputValue, setInputValue] = useState('')
  const debouncedInput = useDebouncedValue(inputValue, 200)

  const { data: options = [], isFetching } = useQuery<T[]>({
    queryKey: [queryKeyPrefix, debouncedInput],
    queryFn: () => searchFn(debouncedInput),
    enabled: debouncedInput.length >= minChars,
    staleTime: 30_000,
  })

  return (
    <Autocomplete<T>
      size="small"
      sx={{ width }}
      options={options}
      loading={isFetching}
      value={value}
      inputValue={inputValue}
      onChange={(_event, next) => onChange(next)}
      onInputChange={(_event, nextInput) => setInputValue(nextInput)}
      getOptionLabel={getOptionLabel}
      isOptionEqualToValue={isOptionEqualToValue}
      filterOptions={(items) => items}
      disabled={disabled}
      renderOption={renderOption}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={placeholder}
        />
      )}
      noOptionsText={inputValue.length < minChars ? `Type at least ${minChars} character${minChars === 1 ? '' : 's'}...` : noOptionsText}
    />
  )
}
