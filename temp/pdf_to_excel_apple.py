import pdfplumber
import pandas as pd
import re
import os
from pathlib import Path

def pdf_to_excel(pdf_path, output_excel_path):
    # Apple statements use "MM/DD/YYYY" for transaction dates
    date_pattern = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.*)")
    
    # Matches amounts at the end of a string, including negative signs (e.g., "-$500.00" or "$54.95")
    amount_pattern = re.compile(r"([\-\s]*\$?[\d,]+\.\d{2})$")
    
    extracted_data = []
    
    current_date = None
    current_desc = ""
    current_amount = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
                
            lines = text.split('\n')

            for line in lines:
                line = line.strip()
                
                # Skip empty lines, basic headers, Apple footers, or summary totals
                if not line or line in ["Date", "Description", "Amount", "Daily Cash"]:
                    continue
                if "Apple Card is issued by" in line or "Goldman Sachs" in line or "Page " in line:
                    continue
                if "Total payments" in line or "Total charges" in line or "Total Daily Cash" in line:
                    continue

                # Check if the line starts with the Apple Date pattern
                match = date_pattern.match(line)
                
                if match:
                    # Save the PREVIOUS transaction before starting a new one
                    if current_date:
                        extracted_data.append([current_date, current_desc.strip(), current_amount])
                    
                    # Start capturing the NEW row
                    current_date = match.group(1)
                    remainder = match.group(2).strip()
                    
                    # Check if the amount is on this first line
                    amt_match = amount_pattern.search(remainder)
                    if amt_match:
                        raw_amount = amt_match.group(1)
                        current_amount = raw_amount.replace(" ", "").replace("$", "").replace(",", "")
                        # Remove the amount from the description
                        current_desc = remainder[:amt_match.start()].strip()
                    else:
                        current_desc = remainder
                        current_amount = "" 
                        
                else:
                    # If the line DOES NOT start with a date, it belongs to the active transaction
                    if current_date:
                        # Check if the amount is isolated on this wrapped line
                        amt_match = amount_pattern.search(line)
                        if amt_match and not current_amount:
                            raw_amount = amt_match.group(1)
                            current_amount = raw_amount.replace(" ", "").replace("$", "").replace(",", "")
                            line_without_amount = line[:amt_match.start()].strip()
                            if line_without_amount:
                                current_desc += " " + line_without_amount
                        else:
                            # Continuation text (like merchant names wrapping to the next line)
                            current_desc += " " + line

    # Catch the very last transaction in the loop
    if current_date:
        extracted_data.append([current_date, current_desc.strip(), current_amount])

    # Convert to Pandas DataFrame
    df = pd.DataFrame(extracted_data, columns=['Date', 'Description', 'Amount'])
    
    # Clean up Description: Strip out Apple Daily Cash indicators (e.g., "$1.10 2%" or "2%")
    df['Description'] = df['Description'].apply(lambda x: re.sub(r"\$?\d+\.\d{2}\s*\d+%\s*$", "", str(x)).strip() if pd.notnull(x) else x)
    df['Description'] = df['Description'].apply(lambda x: re.sub(r"\b\d+%\s*$", "", str(x)).strip() if pd.notnull(x) else x)
    
    # Convert Amount column to numeric, dropping any stray rows that failed to parse a real amount
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
    df = df.dropna(subset=['Amount'])
    
    # Export to Excel
    df.to_excel(output_excel_path, index=False)
    print(f"Success! Data exported to {output_excel_path}")


# --- Run the tool ---
# Make sure to update this folder name to where your Apple Card PDFs are located
bank_statement_folder = "Apple_2026"
bank_statement_folder = os.path.join("Bank_Convert", bank_statement_folder)

if not os.path.exists(bank_statement_folder):
    print(f"Folder '{bank_statement_folder}' not found!")
else:
    pdf_files = list(Path(bank_statement_folder).glob("*.pdf"))
    
    if not pdf_files:
        print(f"No PDF files found in '{bank_statement_folder}'")
    else:
        for pdf_file in pdf_files:
            output_file = pdf_file.stem + ".xlsx"
            output_path = os.path.join(bank_statement_folder, output_file)
            
            print(f"\nProcessing: {pdf_file.name}")
            try:
                pdf_to_excel(str(pdf_file), output_path)
            except Exception as e:
                print(f"Error processing {pdf_file.name}: {e}")