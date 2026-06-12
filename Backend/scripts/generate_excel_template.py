import os
import sys

# Try importing openpyxl, if not present install it
try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
except ImportError:
    import subprocess
    print("Installing openpyxl for Excel generation...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

def create_template():
    wb = openpyxl.Workbook()
    
    # ----------------------------------------------------
    # Tab 1: Daily Pickup Report
    # ----------------------------------------------------
    ws1 = wb.active
    ws1.title = "Daily Pickup Report"
    
    # Title Block
    ws1.merge_cells("A1:I1")
    title_cell = ws1["A1"]
    title_cell.value = "USAV DAILY PICKUP REPORT (BÁO CÁO PICKUP HÀNG NGÀY)"
    title_cell.font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 40
    
    # Headers
    headers1 = [
        "Date (Ngày)", 
        "Carrier (Đơn vị vận chuyển)", 
        "Total Boxes Picked Up (Tổng số thùng đếm thực tế)", 
        "Total Scanned Tracking Numbers (Tổng tracking scan hệ thống)", 
        "Customer Orders Count (Đơn khách lẻ)", 
        "FBA Orders Count (Đơn FBA)", 
        "Checked By (Người đếm)", 
        "Confirmation Photo / Signature (Ảnh xác nhận)",
        "Notes (Ghi chú)"
    ]
    
    header_fill = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
    header_font = Font(name="Arial", size=10, bold=True)
    thin_border = Border(
        left=Side(style='thin', color='B0C4DE'),
        right=Side(style='thin', color='B0C4DE'),
        top=Side(style='thin', color='B0C4DE'),
        bottom=Side(style='thin', color='B0C4DE')
    )
    
    for col_idx, header in enumerate(headers1, 1):
        cell = ws1.cell(row=2, column=col_idx)
        cell.value = header
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws1.row_dimensions[2].height = 28
    
    # Add Sample Rows
    sample_data1 = [
        ["2026-06-12", "UPS", 12, 12, 10, 2, "John Doe", "Signature on file", "Picked up on time"],
        ["2026-06-12", "USPS", 8, 7, 7, 0, "John Doe", "Label photo attached", "Mismatch: 1 missing scan!"],
        ["2026-06-12", "FedEx", 3, 3, 2, 1, "Jane Smith", "Signature on file", ""],
    ]
    
    for row_idx, row_data in enumerate(sample_data1, 3):
        for col_idx, val in enumerate(row_data, 1):
            cell = ws1.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = Alignment(horizontal="left" if col_idx in (2, 7, 8, 9) else "center", vertical="center")
            cell.border = thin_border
        ws1.row_dimensions[row_idx].height = 20
        
    # Auto-fit columns
    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = max(max_len + 3, 12)
        
    # ----------------------------------------------------
    # Tab 2: Tracking Verification
    # ----------------------------------------------------
    ws2 = wb.create_sheet(title="Tracking Verification")
    
    # Title Block
    ws2.merge_cells("A1:H1")
    title_cell2 = ws2["A1"]
    title_cell2.value = "USAV TRACKING VERIFICATION (KIỂM TRA CHÉO TRACKING)"
    title_cell2.font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
    title_cell2.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    title_cell2.alignment = Alignment(horizontal="center", vertical="center")
    ws2.row_dimensions[1].height = 40
    
    headers2 = [
        "Date Verified (Ngày kiểm tra)",
        "Tracking Number (Số Tracking)",
        "Carrier (Vận chuyển)",
        "Order / Shipment ID (Mã Đơn hàng)",
        "Scanned in System? (Có trong HT?)",
        "Physical Box Count Match? (Khớp SL thùng?)",
        "Verified By (Người kiểm tra)",
        "Verification Status / Discrepancy Notes"
    ]
    
    for col_idx, header in enumerate(headers2, 1):
        cell = ws2.cell(row=2, column=col_idx)
        cell.value = header
        cell.font = header_font
        cell.fill = PatternFill(start_color="E4DFEC", end_color="E4DFEC", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws2.row_dimensions[2].height = 28
    
    sample_data2 = [
        ["2026-06-12", "1Z999AA10123456784", "UPS", "13-14737-94831", "YES", "YES", "Alice White", "Verified"],
        ["2026-06-12", "420123459205590123456789012345", "USPS", "4785", "YES", "NO", "Alice White", "Alert: Box was physically picked up but tracking number not marked shipped!"],
    ]
    
    for row_idx, row_data in enumerate(sample_data2, 3):
        for col_idx, val in enumerate(row_data, 1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = Alignment(horizontal="left" if col_idx in (2, 4, 8) else "center", vertical="center")
            cell.border = thin_border
        ws2.row_dimensions[row_idx].height = 20
        
    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = max(max_len + 3, 12)
        
    # Save the file
    filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "USAV_Shipment_Tracking_Template.xlsx")
    wb.save(filepath)
    print(f"Template successfully generated at: {filepath}")

if __name__ == "__main__":
    create_template()
