import csv
import sys
from pathlib import Path

def update_old_items(csv_file_path, output_file_path=None):
    """
    Updates items in a CSV file by:
    1. Prepending '[OLD] - ' to the Item Name
    2. Prepending '[OLD]-' to the SKU (if not empty)
    3. Setting Status to 'Inactive'
    
    Args:
        csv_file_path: Path to the input CSV file
        output_file_path: Path to the output CSV file (defaults to overwriting input)
    """
    
    if output_file_path is None:
        output_file_path = csv_file_path
    
    # Read the CSV file
    rows = []
    fieldnames = []
    
    with open(csv_file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    # Find column indices
    name_col = 'Item Name'
    sku_col = 'SKU'
    status_col = 'Status'
    
    # Verify columns exist
    if not all(col in fieldnames for col in [name_col, sku_col, status_col]):
        print("Error: Required columns not found in CSV file")
        print(f"Expected columns: {name_col}, {sku_col}, {status_col}")
        print(f"Found columns: {fieldnames}")
        sys.exit(1)
    
    # Process each row
    updated_count = 0
    for row in rows:
        # 1. Append '[OLD] - ' to the front of the name
        if row[name_col]:
            row[name_col] = f"[OLD] - {row[name_col]}"
        
        # 2. Append '[OLD]-' to the front of SKU if not empty
        if row[sku_col] and row[sku_col].strip():
            row[sku_col] = f"[OLD]-{row[sku_col]}"
        
        # 3. Change Status to Inactive
        row[status_col] = 'Inactive'
        
        updated_count += 1
    
    # Write the updated data to the output file
    with open(output_file_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"✓ Successfully updated {updated_count} items")
    print(f"✓ Output file: {output_file_path}")

if __name__ == "__main__":
    # Path to the CSV file
    csv_path = Path(__file__).parent.parent.parent / 'misc' / 'Zoho_Old_Item.csv'
    
    if not csv_path.exists():
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)
    
    print(f"Processing: {csv_path}")
    update_old_items(str(csv_path))
    print("Done!")
