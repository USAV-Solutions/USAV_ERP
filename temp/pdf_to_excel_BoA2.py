import pdfplumber
import pandas as pd
import re
import os
from pathlib import Path

def pdf_to_excel(pdf_path, output_excel_path):
    # BoA Bank Statements use MM/DD/YY format (e.g., 12/18/24)
    # This regex makes the description/amount remainder optional to handle multi-line text
    date_pattern = re.compile(r"^(\d{2}/\d{2}/\d{2})(?:\s+(.*))?$")
    
    # Matches amounts at the end of a string, including negative signs
    amount_pattern = re.compile(r"([\-\s]*\$?[\d,]+\.\d{2})$")
    
    extracted_data = []
    
    # State tracking variables
    current_account = "Unknown Account"
    current_category = "Unknown Category"
    
    # Transaction tracking variables
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
                
                # --- 1. Skip Empty lines and Headers ---
                if not line:
                    continue
                if line in ["Date", "Description", "Amount", "Date Description Amount"]:
                    continue
                if "continued on the next page" in line.lower() or "page intentionally left blank" in line.lower():
                    continue
                if "Account #" in line or (line.startswith("Page ") and " of " in line):
                    continue
                if "TOTAL" in line or "Total" in line:
                    # Skip summary lines like "Total deposits and other additions"
                    continue

                # --- 2. Update the "State" (Account & Category) ---
                if "Your Adv Plus Banking" in line:
                    current_account = "Adv Plus Banking"
                    continue
                elif "Your Regular Savings" in line:
                    current_account = "Regular Savings"
                    continue
                    
                if "Deposits and other additions" in line:
                    current_category = "Deposits and other additions"
                    continue
                elif "ATM and debit card subtractions" in line:
                    current_category = "ATM and debit card subtractions"
                    continue
                elif "Other subtractions" in line and "Withdrawals" not in line:
                    # Exclude the top-level header "Withdrawals and other subtractions" to avoid overwrite
                    current_category = "Other subtractions"
                    continue

                # --- 3. Process Transactions ---
                match = date_pattern.match(line)
                
                if match:
                    # Save the PREVIOUS transaction before starting a new one
                    if current_date and current_amount:
                        extracted_data.append([current_account, current_category, current_date, current_desc.strip(), current_amount])
                    
                    # Start capturing the NEW row
                    current_date = match.group(1)
                    remainder = match.group(2)
                    
                    if remainder:
                        remainder = remainder.strip()
                        # Check if the amount is on this exact line
                        amt_match = amount_pattern.search(remainder)
                        if amt_match:
                            raw_amount = amt_match.group(1)
                            current_amount = raw_amount.replace(" ", "").replace("$", "").replace(",", "")
                            current_desc = remainder[:amt_match.start()].strip()
                        else:
                            current_desc = remainder
                            current_amount = "" # Amount might be on the next line
                    else:
                        current_desc = ""
                        current_amount = ""
                        
                else:
                    # If the line DOES NOT start with a date, it belongs to the active transaction
                    if current_date:
                        amt_match = amount_pattern.search(line)
                        if amt_match and not current_amount:
                            raw_amount = amt_match.group(1)
                            current_amount = raw_amount.replace(" ", "").replace("$", "").replace(",", "")
                            
                            # Grab any description text that preceded the amount on this line
                            line_without_amount = line[:amt_match.start()].strip()
                            if line_without_amount:
                                current_desc += " " + line_without_amount
                        else:
                            # Standard continuation text (like a Reference Number)
                            current_desc += " " + line

    # Catch the very last transaction in the loop
    if current_date and current_amount:
        extracted_data.append([current_account, current_category, current_date, current_desc.strip(), current_amount])

    # Convert to Pandas DataFrame with your newly requested columns
    df = pd.DataFrame(extracted_data, columns=['Account', 'Category', 'Date', 'Description', 'Amount'])
    
    # Clean up Description: Strip out 23-digit reference numbers and extra whitespaces
    df['Description'] = df['Description'].apply(lambda x: re.sub(r"\b\d{23}\b", "", str(x)).strip() if pd.notnull(x) else x)
    df['Description'] = df['Description'].apply(lambda x: re.sub(r"\s+", " ", str(x))) # Compress multiple spaces into one
    
    # Convert Amount column to numeric, dropping any stray rows that failed to parse a real amount
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
    df = df.dropna(subset=['Amount'])
    
    # Export to Excel
    df.to_excel(output_excel_path, index=False)
    print(f"Success! Extracted {len(df)} transactions. Data exported to {output_excel_path}")


# --- Run the tool ---
bank_statement_folder = "Fwd_ Re_ Re_Personal Long acc 9148 STATEMENTS"
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