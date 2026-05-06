import pdfplumber
import pandas as pd
import os
import re

def clean_currency(value_str):
    """Converts various currency strings to a clean float."""
    if not value_str or pd.isna(value_str):
        return 0.0
    
    clean_str = str(value_str).replace('$', '').replace(',', '').strip()
    
    if not clean_str:
        return 0.0
        
    try:
        return float(clean_str)
    except ValueError:
        return 0.0

def process_amazon_statement(pdf_path):
    """Extracts data from an Amazon PDF by parsing text layout line-by-line."""
    statement_data = {}
    print(f"Processing: {os.path.basename(pdf_path)}")
    
    with pdfplumber.open(pdf_path) as pdf:
        # layout=True is the magic trick here. It preserves visual spaces!
        text = pdf.pages[0].extract_text(layout=True)
        
        if not text:
            print(f"  -> WARNING: No text found in {os.path.basename(pdf_path)}")
            return statement_data

        # 1. Extract Period and Payment Date
        period_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4}\s*-\s*\d{1,2}/\d{1,2}/\d{4})', text)
        if period_match:
            statement_data['Settlement Period'] = period_match.group(1)
            
        date_match = re.search(r'on\s+(\d{1,2}/\d{1,2}/\d{4})', text)
        if date_match:
            statement_data['Payment Date'] = date_match.group(1)

        # 2. Extract Financial Data Line-by-Line
        main_categories = ['Sales', 'Refunds', 'Expenses']
        current_category = None
        
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Update the main category context if we see it at the start of a line
            for cat in main_categories:
                if line.startswith(cat):
                    current_category = cat
                    break
            
            # Regex to find currency amounts (e.g., $123.45, -$1,234.56, or 123.45)
            # This looks for numbers formatted with two decimals
            amounts = re.findall(r'-?\$?\s*[0-9,]+\.[0-9]{2}', line)
            
            if amounts:
                # Grab the first amount found on the line
                amount_str = amounts[0]
                
                # The label is everything on the line *before* the amount
                label = line.split(amount_str)[0].strip()
                
                # Clean up multiple spaces in the label
                label = re.sub(r'\s+', ' ', label)
                
                if not label:
                    continue
                
                value = clean_currency(amount_str)
                
                # Route the data to the right column name
                if label in ['Beginning Balance', 'Net Proceeds', 'Account Level Reserve']:
                    statement_data[label] = value
                    current_category = None # Reset context
                
                elif label in main_categories:
                    statement_data[f"{label} (Total)"] = value
                
                else:
                    # Append the main category to sub-items so 'Other' doesn't overwrite itself
                    if current_category:
                        col_name = f"{current_category}: {label}"
                    else:
                        col_name = label
                        
                    statement_data[col_name] = value

    return statement_data

def compile_statements_to_excel(pdf_folder, output_file):
    all_data = []
    
    print(f"Scanning folder: {pdf_folder}...")
    for filename in os.listdir(pdf_folder):
        if filename.lower().endswith('.pdf'):
            file_path = os.path.join(pdf_folder, filename)
            try:
                data = process_amazon_statement(file_path)
                if data:
                    data['Source File'] = filename
                    all_data.append(data)
            except Exception as e:
                print(f"Error processing {filename}: {e}")

    if all_data:
        df = pd.DataFrame(all_data)
        
        # Reorder priority columns
        cols = df.columns.tolist()
        priority_cols = ['Source File', 'Settlement Period', 'Payment Date', 'Beginning Balance', 'Net Proceeds']
        
        for col in reversed(priority_cols):
            if col in cols:
                cols.insert(0, cols.pop(cols.index(col)))
                
        df = df[cols]
        df.to_excel(output_file, index=False)
        print(f"\nSuccess! Excel file saved to: {output_file}")
    else:
        print("\nNo PDF data was extracted.")

if __name__ == "__main__":
    INPUT_FOLDER = r"C:/myspace/USAV/ZohoIntegration/Bank_Convert/amazon_statement/PDF" 
    OUTPUT_EXCEL = r"C:/myspace/USAV/ZohoIntegration/Bank_Convert/Amazon_Statements_Compiled.xlsx"
    
    compile_statements_to_excel(INPUT_FOLDER, OUTPUT_EXCEL)