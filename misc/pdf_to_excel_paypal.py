import pdfplumber
import pandas as pd
import re
import os
from pathlib import Path

def parse_paypal_pdf(pdf_path, output_excel_path):
    extracted_data = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Extract tables rather than raw text, as PayPal uses structured grids
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # Clean up empty cells (None)
                    row = [str(cell).strip() if cell else "" for cell in row]
                    
                    # Ensure the row has enough columns and starts with a Date (e.g., 4/1/26)
                    if not row or not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}", row[0]):
                        continue
                        
                    date = row[0].split('\n')[0].strip() # Take just the first date if lines merged
                    desc = ""
                    name_email = ""
                    gross = ""
                    fee = ""
                    net = ""
                    
                    # PayPal sometimes formats tables with 6 columns, or merges columns down to 5
                    if len(row) >= 6:
                        # Standard Layout: Date | Description | Name Email | Gross | Fee | Net
                        desc = row[1]
                        name_email = row[2]
                        gross = row[3]
                        fee = row[4]
                        net = row[5]
                    elif len(row) == 5:
                        # 5-Column Layout: Date | Name/Email & Description | Gross | Fee | Net
                        combined_text = row[1]
                        gross = row[2]
                        fee = row[3]
                        net = row[4]
                        
                        # Separate Description from Name/Email using 'ID:' as the anchor point
                        id_match = re.search(r"(ID:\s*[A-Z0-9]+)", combined_text)
                        if id_match:
                            split_point = id_match.end()
                            desc = combined_text[:split_point].strip()
                            name_email = combined_text[split_point:].strip()
                        else:
                            desc = combined_text

                    # --- 1 & 2. Extract Type and ID from Description ---
                    trans_type = desc
                    trans_id = ""
                    
                    if "ID:" in desc:
                        parts = desc.split("ID:", 1)
                        trans_type = parts[0].strip()
                        trans_id = parts[1].strip()
                        
                    # Flatten the Type if split into two lines
                    trans_type = " ".join(trans_type.split())
                    
                    # --- 3 & 4. Extract Name and Email from Name/Email ---
                    email = ""
                    name = ""
                    
                    if name_email:
                        lines = name_email.split('\n')
                        # Find the single line with the '@' symbol
                        email_lines = [l.strip() for l in lines if "@" in l]
                        # The remaining lines belong to the Name
                        name_lines = [l.strip() for l in lines if "@" not in l]
                        
                        if email_lines:
                            email = email_lines[0]
                            
                        # Flatten the Name if split into two lines
                        name = " ".join(name_lines)
                        name = " ".join(name.split())
                        
                    # Clean Amount Columns (strip dollar signs/commas, keep decimals/negative signs)
                    gross = re.sub(r'[^\d\.\-]', '', gross)
                    fee = re.sub(r'[^\d\.\-]', '', fee)
                    net = re.sub(r'[^\d\.\-]', '', net)
                    
                    # Add to our final dataset
                    extracted_data.append([
                        date, trans_type, trans_id, name, email, gross, fee, net
                    ])

    # Convert to Pandas DataFrame using requested columns
    df = pd.DataFrame(extracted_data, columns=['Date', 'Type', 'ID', 'Name', 'Email', 'Gross', 'Fee', 'Net'])
    
    # Convert amounts back to numbers for Excel calculations
    for col in ['Gross', 'Fee', 'Net']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    # Export to Excel
    df.to_excel(output_excel_path, index=False)
    print(f"Success! Data exported to {output_excel_path}")


# --- Run the tool ---
bank_statement_folder = "Bank_Convert"
bank_statement_folder = os.path.join(bank_statement_folder, "paypal")

if not os.path.exists(bank_statement_folder):
    os.makedirs(bank_statement_folder)
    print(f"Created folder '{bank_statement_folder}'. Please place your PayPal PDFs inside and re-run.")
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
                parse_paypal_pdf(str(pdf_file), output_path)
            except Exception as e:
                print(f"Error processing {pdf_file.name}: {e}")