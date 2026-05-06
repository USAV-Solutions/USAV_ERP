import pdfplumber
import pandas as pd
import re
import os
from pathlib import Path

def pdf_to_excel_chase(pdf_path, output_excel_path):
    # Chase statements use a single "MM/DD" for dates
    date_pattern = re.compile(r"^(\d{2}/\d{2})\s+(.*)")
    
    # Matches amounts at the end of a string, including negative signs (e.g., "-24.98")
    amount_pattern = re.compile(r"([\-\s]*\$?[\d,]+\.\d{2})$")
    
    extracted_data = []
    
    # Defaults for year-boundary calculations
    statement_month = "01" 
    statement_year = "25" 
    
    current_date = None
    current_desc = ""
    current_amount = ""
    
    in_activity_section = False

    with pdfplumber.open(pdf_path) as pdf:
        # 1. Attempt to extract the statement date/year from the first page
        first_page_text = pdf.pages[0].extract_text()
        if first_page_text:
            # Looks for dates like 01/26/25 to figure out the statement year
            date_match = re.search(r"(\d{2})/\d{2}/(\d{2})", first_page_text)
            if date_match:
                statement_month = date_match.group(1)
                statement_year = date_match.group(2)

        # 2. Iterate through pages and parse transactions
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
                
            lines = text.split('\n')

            for line in lines:
                line = line.strip()
                
                # The PDF extractor messes up the "ACCOUNT ACTIVITY" header, 
                # so we trigger ON when we see the column headers instead.
                if "Merchant Name or Transaction Description" in line:
                    # Make sure we aren't in the Shop with Points section!
                    if "Rewards" in line:
                        in_activity_section = False
                    else:
                        in_activity_section = True
                    continue
                
                # Turn parsing OFF when we hit summaries
                if "Totals Year-to-Date" in line or "Year-to-Date" in line or "IINNTTEERREESSTT" in line:
                    in_activity_section = False
                    
                if not in_activity_section:
                    continue

                # Skip empty lines and header rows within the table
                if not line or "Date of" in line or "Transaction" in line or "PAYMENTS AND OTHER CREDITS" in line or line == "PURCHASE" or line == "PURCHASES":
                    continue

                # Check if the line starts with the Chase Date pattern
                match = date_pattern.match(line)
                
                if match:
                    # Save the PREVIOUS transaction before starting a new one
                    if current_date:
                        extracted_data.append([current_date, current_desc.strip(), current_amount])
                    
                    # Start capturing the NEW row
                    post_date = match.group(1)
                    txn_month = post_date.split('/')[0]
                    txn_year = statement_year
                    
                    # Year boundary handling (e.g., Dec transaction on a Jan statement)
                    if statement_month == "01" and txn_month == "12":
                        txn_year = str(int(statement_year) - 1).zfill(2)
                        
                    current_date = f"{post_date}/20{txn_year}"
                    
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
                            # Continuation text (like an Amazon Order Number)
                            current_desc += " " + line

    # Catch the very last transaction in the loop
    if current_date and current_amount:
        extracted_data.append([current_date, current_desc.strip(), current_amount])

    # Convert to Pandas DataFrame
    df = pd.DataFrame(extracted_data, columns=['Date', 'Description', 'Amount'])
    
    # Convert Amount column to numeric, dropping any stray rows that failed to parse a real amount
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
    df = df.dropna(subset=['Amount'])
    
    # Export to Excel
    df.to_excel(output_excel_path, index=False)
    print(f"Success! Data exported to {output_excel_path}")


# --- Run the tool ---
# UPDATE THIS FOLDER PATH TO MATCH YOURS
bank_statement_folder = "Fwd_ CHASE BANK STATEMENTS" 
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
                pdf_to_excel_chase(str(pdf_file), output_path)
            except Exception as e:
                print(f"Error processing {pdf_file.name}: {e}")