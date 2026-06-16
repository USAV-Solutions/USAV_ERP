import React, { useState } from 'react'
import {
  Box,
  Typography,
  IconButton,
  TextField,
  Button,
  Grid,
} from '@mui/material'
import { Delete as DeleteIcon, Add as AddIcon } from '@mui/icons-material'
import { EbayAspectValue } from '../../types/ebayListing'

interface ItemSpecificsEditorProps {
  aspects: EbayAspectValue[]
  onChange: (aspects: EbayAspectValue[]) => void
}

export default function ItemSpecificsEditor({ aspects, onChange }: ItemSpecificsEditorProps) {
  const [newAspectName, setNewAspectName] = useState('')
  const [newAspectValue, setNewAspectValue] = useState('')

  const handleUpdateAspect = (index: number, value: string) => {
    const updated = [...aspects]
    updated[index] = { ...updated[index], values: [value] }
    onChange(updated)
  }

  const handleRemoveAspect = (index: number) => {
    const updated = [...aspects]
    updated.splice(index, 1)
    onChange(updated)
  }

  const handleAddAspect = () => {
    if (newAspectName.trim() && newAspectValue.trim()) {
      onChange([
        ...aspects,
        {
          name: newAspectName.trim(),
          values: [newAspectValue.trim()],
          required: false,
        },
      ])
      setNewAspectName('')
      setNewAspectValue('')
    }
  }

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 2 }}>
        Item Specifics
      </Typography>
      {aspects.map((aspect, idx) => (
        <Grid container spacing={2} key={idx} sx={{ mb: 1 }} alignItems="center">
          <Grid item xs={4}>
            <Typography variant="body2" sx={{ fontWeight: aspect.required ? 'bold' : 'normal' }}>
              {aspect.name} {aspect.required && <span style={{ color: 'red' }}>*</span>}
            </Typography>
          </Grid>
          <Grid item xs={7}>
            <TextField
              size="small"
              fullWidth
              value={aspect.values[0] || ''}
              onChange={(e) => handleUpdateAspect(idx, e.target.value)}
              placeholder="Value"
            />
          </Grid>
          <Grid item xs={1}>
            {!aspect.required && (
              <IconButton size="small" onClick={() => handleRemoveAspect(idx)} color="error">
                <DeleteIcon fontSize="small" />
              </IconButton>
            )}
          </Grid>
        </Grid>
      ))}

      <Box sx={{ mt: 3, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
        <Typography variant="body2" sx={{ mb: 1, fontWeight: 'bold' }}>
          Add Custom Specific
        </Typography>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={4}>
            <TextField
              size="small"
              fullWidth
              placeholder="Name (e.g., Year)"
              value={newAspectName}
              onChange={(e) => setNewAspectName(e.target.value)}
            />
          </Grid>
          <Grid item xs={5}>
            <TextField
              size="small"
              fullWidth
              placeholder="Value (e.g., 2023)"
              value={newAspectValue}
              onChange={(e) => setNewAspectValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddAspect()
              }}
            />
          </Grid>
          <Grid item xs={3}>
            <Button
              variant="outlined"
              size="small"
              startIcon={<AddIcon />}
              onClick={handleAddAspect}
              disabled={!newAspectName.trim() || !newAspectValue.trim()}
              fullWidth
            >
              Add
            </Button>
          </Grid>
        </Grid>
      </Box>
    </Box>
  )
}
