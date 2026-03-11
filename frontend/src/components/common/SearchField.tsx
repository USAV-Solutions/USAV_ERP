import { ChangeEvent } from 'react'
import { TextField, InputAdornment, TextFieldProps } from '@mui/material'
import { Search } from '@mui/icons-material'

interface SearchFieldProps {
  value: string
  placeholder?: string
  size?: TextFieldProps['size']
  fullWidth?: boolean
  sx?: TextFieldProps['sx']
  onChange: (value: string) => void
}

export default function SearchField({
  value,
  placeholder,
  size = 'small',
  fullWidth = false,
  sx,
  onChange,
}: SearchFieldProps) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange(event.target.value)
  }

  return (
    <TextField
      value={value}
      onChange={handleChange}
      placeholder={placeholder}
      size={size}
      fullWidth={fullWidth}
      sx={sx}
      InputProps={{
        startAdornment: (
          <InputAdornment position="start">
            <Search />
          </InputAdornment>
        ),
      }}
    />
  )
}
