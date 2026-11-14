import httpx


async def ensure_sheet_tab(spreadsheet_id: str, tab_name: str, token: str) -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
            f"?fields=sheets.properties.title",
            headers={"Authorization": f"Bearer {token}"},
        )

    if r.status_code == 401:
        raise Exception("GOOGLE_TOKEN_EXPIRED")
    if not r.is_success:
        raise Exception(f"Sheets API error {r.status_code}: {r.text}")

    existing = [s["properties"]["title"] for s in r.json().get("sheets", [])]
    if tab_name in existing:
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
        )

    if response.status_code == 401:
        raise Exception("GOOGLE_TOKEN_EXPIRED")
    if not response.is_success:
        raise Exception(f"Sheets API error {response.status_code}: {response.text}")


async def append_rows_to_sheet(
    spreadsheet_id: str,
    sheet_name: str,
    rows: list[list[str]],
    token: str,
) -> dict:
    range_encoded = f"{sheet_name}!A1".replace(" ", "%20")
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{range_encoded}:append"
        f"?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"values": rows},
        )

    if response.status_code == 401:
        raise Exception("GOOGLE_TOKEN_EXPIRED")

    if not response.is_success:
        raise Exception(f"Sheets API error {response.status_code}: {response.text}")

    return response.json()
