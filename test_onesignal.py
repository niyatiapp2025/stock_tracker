import requests

# OneSignal Configuration
ONESIGNAL_API_KEY = "os_v2_app_flemraywrrfczap5lf54vaqxpmaclo6ceunus6mkir6nay4nyd6sd374zuwuggryxteo2udfrxzrrc4yrxxcxlyfmbm4bs6zqtmsrca"
ONESIGNAL_APP_ID = "2ac8c883-168c-4a2c-81fd-597bca82177b"

def test_onesignal_notification():
    """Test OneSignal push notification"""
    try:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": ONESIGNAL_API_KEY
        }
        payload = {
            "app_id": ONESIGNAL_APP_ID,
            "target_channel": "push",
            "headings": {"en": "🧪 Test Notification"},
            "contents": {"en": "OneSignal integration is working! You should receive this notification on your subscribed devices."},
            "included_segments": ["Total Subscriptions"]
        }
        
        print("Sending test notification to OneSignal...")
        print(f"App ID: {ONESIGNAL_APP_ID}")
        print(f"Endpoint: https://api.onesignal.com/notifications")
        print("-" * 50)
        
        response = requests.post(
            "https://api.onesignal.com/notifications",
            headers=headers,
            json=payload
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        print("-" * 50)
        
        if response.status_code == 200:
            print("✅ SUCCESS! Notification sent successfully.")
            print("Check your subscribed devices for the notification.")
            response_data = response.json()
            if 'id' in response_data:
                print(f"Notification ID: {response_data['id']}")
            if 'recipients' in response_data:
                print(f"Recipients: {response_data['recipients']}")
        else:
            print(f"❌ ERROR: Failed to send notification.")
            print(f"Status: {response.status_code}")
            print(f"Details: {response.text}")
            
    except Exception as e:
        print(f"❌ EXCEPTION: {e}")

if __name__ == "__main__":
    test_onesignal_notification()

