# Daily Automated Tasks Walkthrough

I have successfully created the Python automation script to handle your daily synchronizations.

## What Was Completed
- **Script Created:** `Backend/scripts/daily_automated_tasks.py` is now fully written and executable.
- **Smart Dates:** The script dynamically calculates the dates every time it runs (`since = now() - 10 days`, `until = now()`).
- **Endpoint Targeting:** The script authentically logs into your running FastAPI backend and sequentially fires off:
  - `POST /orders/sync/range`
  - `POST /purchases/import/zoho`
  - `POST /purchases/backfill-delivery-status`
- **Auto-Cleaning Logs:** Implemented Python's native `TimedRotatingFileHandler` which will save the logs safely into `Backend/logs/daily_tasks/daily_sync.log` and automatically delete old logs after 7 days without needing a separate deletion script.

## Setup Instructions

> [!IMPORTANT]  
> You must ensure your `Backend/.env` file has the new variables configured for the script to be able to authenticate with the backend API:
> ```env
> ADMIN_USERNAME=your_admin_email_or_username
> ADMIN_PASSWORD=your_secure_password
> ```

### Scheduling the Job

To set this to run automatically at 08:30 AM GMT+7 every morning, you'll need to add it to your server's Linux `crontab`.

1. On your server, open the terminal and type:
   ```bash
   crontab -e
   ```
2. Paste the following line at the bottom of the file (assuming your server's system time is set to GMT+7, if not, adjust the `30 8` to match the GMT equivalent):
   ```cron
   30 8 * * * cd /home/las/USAV/USAV_Inventory/Backend && ./scripts/daily_automated_tasks.py
   ```
3. Save and close. Cron will now automatically kick off the jobs exactly at 8:30 AM every day.

> [!TIP]
> If you prefer to have the agent run this on a recurring schedule without involving Linux system cron, you can use the `/schedule` slash command in the chat UI!