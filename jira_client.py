import requests
import pandas as pd


def _headers(api_token: str) -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_token}",
    }


def _error_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
        messages = body.get("errorMessages", [])
        errors = body.get("errors", {})
        if messages:
            return "; ".join(messages)
        if errors:
            return "; ".join(f"{k}: {v}" for k, v in errors.items())
    except Exception:
        pass
    return resp.text or f"HTTP {resp.status_code}"


def fetch_issues_by_jql(
    jira_url: str,
    api_token: str,
    jql: str,
    tracking_field_id: str,
    external_id_field_id: str = "",
) -> pd.DataFrame:
    """Fetch all issues matching a JQL query (paginated)."""
    url = f"{jira_url.rstrip('/')}/rest/api/2/search"
    extra = f",{external_id_field_id}" if external_id_field_id else ""
    fields = f"summary,description,issuetype,status,labels,{tracking_field_id}{extra}"
    headers = _headers(api_token)

    all_issues = []
    start_at = 0
    max_results = 100

    while True:
        params = {
            "jql": jql,
            "fields": fields,
            "startAt": start_at,
            "maxResults": max_results,
        }
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"Jira API error ({resp.status_code}): {_error_message(resp)}")

        data = resp.json()
        page = data.get("issues", [])
        all_issues.extend(page)

        if start_at + len(page) >= data.get("total", 0):
            break
        start_at += max_results

    return _normalize_issues(all_issues, tracking_field_id, external_id_field_id)


def fetch_single_issue(
    jira_url: str,
    api_token: str,
    issue_key: str,
    tracking_field_id: str,
    external_id_field_id: str = "",
) -> dict:
    """Fetch a single issue by key. Returns a normalized row dict."""
    url = f"{jira_url.rstrip('/')}/rest/api/2/issue/{issue_key}"
    extra = f",{external_id_field_id}" if external_id_field_id else ""
    fields = f"summary,description,issuetype,status,labels,{tracking_field_id}{extra}"
    resp = requests.get(url, headers=_headers(api_token), params={"fields": fields}, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Jira API error ({resp.status_code}): {_error_message(resp)}")

    issue = resp.json()
    f = issue.get("fields", {})
    return {
        "Issue Key":   issue["key"],
        "Summary":     f.get("summary", ""),
        "Description": f.get("description", "") or "",
        "Issue Type":  (f.get("issuetype") or {}).get("name", ""),
        "Status":      (f.get("status") or {}).get("name", ""),
        "Labels":      ", ".join(f.get("labels") or []),
        "External ID": f.get(external_id_field_id, "") if external_id_field_id else "",
        "Tracking ID": f.get(tracking_field_id, ""),
    }


def _normalize_issues(raw_issues: list, tracking_field_id: str, external_id_field_id: str = "") -> pd.DataFrame:
    rows = []
    for issue in raw_issues:
        f = issue.get("fields", {})
        rows.append({
            "Issue Key":   issue["key"],
            "Summary":     f.get("summary", ""),
            "Description": f.get("description", "") or "",
            "Issue Type":  (f.get("issuetype") or {}).get("name", ""),
            "Status":      (f.get("status") or {}).get("name", ""),
            "Labels":      ", ".join(f.get("labels") or []),
            "External ID": f.get(external_id_field_id, "") if external_id_field_id else "",
            "Tracking ID": f.get(tracking_field_id, ""),
        })
    return pd.DataFrame(rows)


def list_custom_fields(jira_url: str, api_token: str) -> pd.DataFrame:
    """Return a DataFrame of all custom fields (name, id) for the Jira instance."""
    url = f"{jira_url.rstrip('/')}/rest/api/2/field"
    resp = requests.get(url, headers=_headers(api_token), timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Jira API error ({resp.status_code}): {_error_message(resp)}")

    fields = [
        {"Name": f["name"], "Field ID": f["id"]}
        for f in resp.json()
        if f.get("custom", False)
    ]
    return pd.DataFrame(fields).sort_values("Name").reset_index(drop=True)


def update_tracking_ids(
    jira_url: str,
    api_token: str,
    ordered_df: pd.DataFrame,
    tracking_field_id: str,
) -> list:
    """
    Update the Tracking ID custom field on each issue in order.
    Returns a list of result dicts: {"key": ..., "status": "ok" | "error", "detail": ...}
    """
    base_url = jira_url.rstrip("/")
    headers = _headers(api_token)
    results = []

    for _, row in ordered_df.iterrows():
        issue_key = row["Issue Key"]
        url = f"{base_url}/rest/api/2/issue/{issue_key}"
        padded_rank = str(row["Rank"])
        payload = {"fields": {tracking_field_id: padded_rank}}

        try:
            resp = requests.put(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 204:
                results.append({"key": issue_key, "status": "ok", "detail": ""})
            else:
                results.append({
                    "key": issue_key,
                    "status": "error",
                    "detail": f"HTTP {resp.status_code}: {_error_message(resp)}",
                })
        except requests.exceptions.RequestException as e:
            results.append({"key": issue_key, "status": "error", "detail": str(e)})

    return results
