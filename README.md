# Daily Zoho to Google Sheets sync

Refreshes the existing **Employee Work Mode** worksheet daily around **09:00 IST** (03:30 UTC), including weekends. Also supports a manual run from Actions. GitHub can delay scheduled jobs, so the start time is approximate.

The original destination is selected through `GOOGLE_SHEET_ID`; the script does not create a replacement spreadsheet. All destination and Zoho identifiers live in Actions secrets. This public repository contains no employee records, session cookies, service-account keys, or organization-specific identifiers.

## Setup

In this repository, open **Settings → Secrets and variables → Actions** and add these **repository secrets**:

| Secret | Value |
|---|---|
| `ZOHO_URL` | Original Zoho `viewAction.zp` URL |
| `ZOHO_FORM_ID` | Original `FORM_ID` |
| `ZOHO_VIEW_ID` | Original `VIEW_ID` |
| `GOOGLE_SHEET_ID` | Original `SHEET_ID`, keeping the destination unchanged |
| `ZOHO_COOKIES` | Full Cookie request-header value from a fresh authenticated Zoho session, without the `Cookie:` label |
| `ZOHO_CSRF_TOKEN` | Matching `conreqcsr` token from the same session |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Complete JSON key for the Google service account |

Create a Google Cloud service account in a project with the **Google Sheets API enabled**. No project-wide IAM role is required. Create its JSON key, store it in the secret above, and share the **existing destination spreadsheet** with its `client_email` address as an **Editor**. If organization policy restricts keys or sharing, use an administrator-approved setup.

Open **Actions → Daily Zoho to Google Sheets → Run workflow** on the default branch to test. Confirm success and check the existing worksheet's timestamp. With the workflow on the default branch and Actions enabled, GitHub schedules subsequent daily runs even when your computer is off. For public repositories, GitHub disables scheduled workflows after 60 days without repository activity; re-enable it if that happens.

## Behavior and limitations

- Preserves the original field order, all-employee status filter, header formatting, frozen header, and IST timestamp. Replaces this worksheet's values and clears stale rows; other tabs are unchanged.
- Uses text cells to preserve employee IDs, phone numbers, and formula-like source values.
- Fetches and validates every page before writing. Failed requests, missing record lists, repeated pages, malformed fields, and empty exports stop the sync.
- Advances by each page's actual length and continues until an explicit empty employee list. If Zoho uses a different end-of-results response, it fails safely until that response is supported.
- Writes values, stale-cell cleanup, and formatting in one atomic Sheets batch. If the tab is missing, it is created first; an unsuccessful final write may leave a new empty tab.
- Does not log employee rows, cookies, credentials, or response bodies. Failed runs exit with a failure status. Check GitHub notification preferences for failure alerts.
- Browser-session cookies expire. Refresh both Zoho secrets when needed. A supported OAuth/API integration would be needed to remove that manual maintenance.
- This public repository must never receive the original Colab script with embedded cookies, credentials JSON, or employee exports. Keep all such material in secrets or outside the repository.

## References

- [GitHub scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [gspread service-account setup](https://docs.gspread.org/en/latest/oauth2.html#for-bots-using-service-account)
- [Atomic Sheets batches](https://developers.google.com/workspace/sheets/api/guides/batch)
