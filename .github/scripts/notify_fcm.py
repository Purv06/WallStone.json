#!/usr/bin/env python3
"""
Automated Firebase Cloud Messaging (FCM) Notification Broadcaster
Triggered by GitHub Actions on push when WallStone catalog is updated.
Broadcasts a push notification to all users subscribed to topic 'wallpapers'.
"""

import os
import sys
import json
import subprocess

# Ensure UTF-8 output encoding across all operating systems
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def find_catalog_file():
    candidates = ["Wallstone", "Wallstone.json", "Wallstone_catalog_renamed.json"]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

def extract_added_wallpapers(catalog_path):
    """
    Attempts to identify newly added wallpapers by comparing git diff HEAD~1 against current catalog.
    Falls back to inspecting top items if diff analysis is unavailable.
    """
    added_wallpapers = []

    # 1. Parse JSON diff between HEAD~1 and HEAD
    try:
        prev_content_cmd = ["git", "show", f"HEAD~1:{catalog_path}"]
        prev_raw = subprocess.check_output(prev_content_cmd, text=True, stderr=subprocess.DEVNULL)
        prev_catalog = json.load(prev_raw)
        prev_urls = {item.get("url") for item in prev_catalog if isinstance(item, dict) and item.get("url")}

        with open(catalog_path, "r", encoding="utf-8") as f:
            curr_catalog = json.load(f)

        for item in curr_catalog:
            if isinstance(item, dict) and item.get("url") and item.get("url") not in prev_urls:
                added_wallpapers.append(item)

        if added_wallpapers:
            return added_wallpapers
    except Exception:
        pass

    # 2. Fallback: inspect added diff lines for unique URLs
    try:
        diff_cmd = ["git", "diff", "HEAD~1", "HEAD", "--", catalog_path]
        diff_output = subprocess.check_output(diff_cmd, text=True, stderr=subprocess.DEVNULL)
        added_lines = [line[1:].strip() for line in diff_output.splitlines() if line.startswith("+") and not line.startswith("+++")]
        diff_content = "\n".join(added_lines)

        with open(catalog_path, "r", encoding="utf-8") as f:
            curr_catalog = json.load(f)

        for item in curr_catalog:
            url = item.get("url", "")
            if url and url in diff_content:
                added_wallpapers.append(item)
        if added_wallpapers:
            return added_wallpapers
    except Exception:
        pass

    # 3. Final fallback: top item in catalog
    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                added_wallpapers = [data[0]]
    except Exception as e:
        print(f"Error reading catalog: {e}")

    return added_wallpapers

def build_notification_content(added_wallpapers):
    count = len(added_wallpapers)
    if count == 0:
        return None

    first = added_wallpapers[0]
    name = first.get("name", "New Wallpaper")
    collection = first.get("collections", "WallStone")
    image_url = first.get("thumbnail") or first.get("url")

    if count == 1:
        title = f"New Wallpaper Added: {name} 🎨"
        body = f"A fresh {collection} wallpaper is now available in WallStone. Tap to apply!"
    else:
        title = f"{count} New Wallpapers Added! 🎨"
        body = f"Fresh wallpapers including '{name}' in {collection} are live in WallStone. Check them out!"

    return {
        "title": title,
        "body": body,
        "image_url": image_url,
        "wallpaper_name": name,
        "collection": collection,
        "count": count
    }

def send_fcm_notification(project_id, service_account_json_str, content):
    """
    Sends notification using Google OAuth2 and FCM HTTP v1 API.
    """
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        import requests
    except ImportError:
        print("Required libraries missing. Install: pip install google-auth requests")
        return False

    try:
        service_account_info = json.loads(service_account_json_str)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        credentials.refresh(Request())
        access_token = credentials.token
    except Exception as e:
        print(f"Failed to authenticate with Firebase Service Account: {e}")
        return False

    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; UTF-8",
    }

    # Broadcast to 'wallpapers' topic
    payload = {
        "message": {
            "topic": "wallpapers",
            "notification": {
                "title": content["title"],
                "body": content["body"]
            },
            "data": {
                "title": content["title"],
                "body": content["body"],
                "image_url": content["image_url"] or "",
                "wallpaper_name": content["wallpaper_name"] or "",
                "collection": content["collection"] or ""
            },
            "android": {
                "priority": "HIGH",
                "notification": {
                    "channel_id": "wallstone_new_wallpapers",
                    "default_sound": True,
                    "default_vibrate_timings": True
                }
            }
        }
    }

    if content["image_url"]:
        payload["message"]["notification"]["image"] = content["image_url"]
        payload["message"]["android"]["notification"]["image"] = content["image_url"]

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"Successfully broadcast FCM notification: {response.json()}")
        return True
    else:
        print(f"FCM error response ({response.status_code}): {response.text}")
        return False

def main():
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "wallstone-f36f4")
    service_account_str = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()

    catalog_path = find_catalog_file()
    if not catalog_path:
        print("Could not find WallStone catalog file. Aborting.")
        sys.exit(0)

    print(f"Analyzing catalog: {catalog_path}")
    added = extract_added_wallpapers(catalog_path)
    if not added:
        print("No new wallpapers detected.")
        sys.exit(0)

    content = build_notification_content(added)
    print("\n--- Notification Preview ---")
    print(f"Title: {content['title']}")
    print(f"Body:  {content['body']}")
    print(f"Image: {content['image_url']}")
    print(f"Topic: wallpapers")
    print("----------------------------\n")

    if not service_account_str:
        print("NOTICE: FIREBASE_SERVICE_ACCOUNT_JSON secret is not set.")
        print("To enable automatic live push notifications:")
        print("1. Go to GitHub repo (Purv06/WallStone.json) -> Settings -> Secrets and variables -> Actions")
        print("2. Click 'New repository secret'")
        print("3. Name: FIREBASE_SERVICE_ACCOUNT_JSON")
        print("4. Value: Paste contents of wallstone-f36f4-firebase-adminsdk-fbsvc-12177e7f3e.json")
        print("\nSimulation complete. Notification formatted successfully.")
        sys.exit(0)

    success = send_fcm_notification(project_id, service_account_str, content)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
