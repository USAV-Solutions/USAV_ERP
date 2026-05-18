import pdfplumber
import pandas as pd
import re
import os
from pathlib import Path

def pdf_to_excel_paypal(pdf_path, output_excel_path):
    # Match PayPal dates like "4/1/26" or "12/31/2026"
    date_pattern = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4})\s+(.*)")
    
    # Matches the THREE amounts at the end of the row: Gross, Fee, Net (e.g., "157.43 -5.98 151.45")
    amounts_pattern = re.compile(r"([\-\s]*\$?[\d,]+\.\d{2})\s+([\-\s]*\$?[\d,]+\.\d{2})\s+([\-\s]*\$?[\d,]+\.\d{2})$")
    
    extracted_data = []
    
    in_transaction_history = False
    
    current_date = None
    current_desc = ""
    current_gross = ""
    current_fee = ""
    current_net = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
                
            # Trigger parsing ONLY when we reach the Transaction History section
            if "Transaction History" in text:
                in_transaction_history = True
                
            if not in_transaction_history:
                continue

            lines = text.split('\n')

            for line in lines:
                line = line.strip()
                
                # Skip empty lines, headers, and standard PayPal footers
                if (not line or line.startswith("Date") or "Page" in line or 
                    "PayPal ID:" in line or "Transaction History" in line or 
                    "To report an unauthorized" in line or "Merchant Account ID" in line):
                    continue

                # Check if the line starts with the Date pattern
                match = date_pattern.match(line)
                
                if match:
                    # Save the PREVIOUS transaction before starting a new one
                    if current_date:
                        extracted_data.append([current_date, current_desc.strip(" |"), current_gross, current_fee, current_net])
                    
                    # Start capturing the NEW row
                    current_date = match.group(1)
                    remainder = match.group(2).strip()
                    
                    # Check if the 3 amounts are on this first line
                    amt_match = amounts_pattern.search(remainder)
                    if amt_match:
                        current_gross = amt_match.group(1).replace(" ", "").replace("$", "").replace(",", "")
                        current_fee = amt_match.group(2).replace(" ", "").replace("$", "").replace(",", "")
                        current_net = amt_match.group(3).replace(" ", "").replace("$", "").replace(",", "")
                        
                        # Remove the amounts from the description
                        current_desc = remainder[:amt_match.start()].strip()
                    else:
                        current_desc = remainder
                        current_gross = current_fee = current_net = "" 
                        
                else:
                    # If the line DOES NOT start with a date, it belongs to the active transaction
                    if current_date:
                        # Check if the amounts are isolated on this wrapped line
                        amt_match = amounts_pattern.search(line)
                        if amt_match and not current_gross:
                            current_gross = amt_match.group(1).replace(" ", "").replace("$", "").replace(",", "")
                            current_fee = amt_match.group(2).replace(" ", "").replace("$", "").replace(",", "")
                            current_net = amt_match.group(3).replace(" ", "").replace("$", "").replace(",", "")
                            
                            line_without_amount = line[:amt_match.start()].strip()
                            if line_without_amount:
                                current_desc += " | " + line_without_amount
                        else:
                            # Continuation text (Description / Name / Email / Transaction ID)
                            current_desc += " | " + line

    # Catch the very last transaction in the loop
    if current_date:
        extracted_data.append([current_date, current_desc.strip(" |"), current_gross, current_fee, current_net])

    # Convert to Pandas DataFrame
    df = pd.DataFrame(extracted_data, columns=['Date', 'Description & Name', 'Gross', 'Fee', 'Net'])
    
    # Convert financial columns to numeric floats
    for col in ['Gross', 'Fee', 'Net']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    # Drop rows that failed to parse a real Net amount (filters out lingering junk data)
    df = df.dropna(subset=['Net'])
    
    # Export to Excel
    df.to_excel(output_excel_path, index=False)
    print(f"Success! Data exported to {output_excel_path}")


# --- Run the tool ---
# Make sure to update the folder name to where your PayPal PDFs are stored
statement_folder = "paypal" 
statement_folder = os.path.join("Bank_Convert", statement_folder)

if not os.path.exists(statement_folder):
    print(f"Folder '{statement_folder}' not found!")
else:
    pdf_files = list(Path(statement_folder).glob("*.pdf"))
    
    if not pdf_files:
        print(f"No PDF files found in '{statement_folder}'")
    else:
        for pdf_file in pdf_files:
            output_file = pdf_file.stem + "_PayPal.xlsx"
            output_path = os.path.join(statement_folder, output_file)
            
            print(f"\nProcessing: {pdf_file.name}")
            try:
                pdf_to_excel_paypal(str(pdf_file), output_path)
            except Exception as e:
                print(f"Error processing {pdf_file.name}: {e}")